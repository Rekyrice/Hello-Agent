import os
import re
from typing import Dict, Optional, Tuple

import requests
from dotenv import load_dotenv
from openai import OpenAI
from tavily import TavilyClient

AGENT_SYSTEM_PROMPT = """
你是一个智能旅行助手。你的任务是分析用户的请求，并使用可用工具一步步地解决问题。

# 可用工具:
- `get_weather(city: str)`: 查询指定城市的实时天气。
- `get_attraction(city: str, weather: str)`: 根据城市和天气搜索推荐的旅游景点。

# 输出格式要求:
你的每次回复必须严格遵循以下格式，包含一对Thought和Action：

Thought: [你的思考过程和下一步计划]
Action: [你要执行的具体行动]

Action的格式必须是以下之一：
1. 调用工具：function_name(arg_name="arg_value")
2. 结束任务：Finish[最终答案]

# 重要提示:
- 每次只输出一对Thought-Action
- Action必须在同一行，不要换行
- 当收集到足够信息可以回答用户问题时，必须使用 Action: Finish[最终答案] 格式结束

请开始吧！
"""

WEATHER_TIMEOUT_SECONDS = 12
_tavily_client: Optional[TavilyClient] = None


def get_env_or_raise(name: str) -> str:
    """读取必填环境变量，缺失时抛出异常。"""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"缺少必填环境变量：{name}")
    return value


def get_tavily_client() -> TavilyClient:
    """按需初始化 Tavily 客户端，避免每次重复创建。"""
    global _tavily_client
    if _tavily_client is None:
        api_key = get_env_or_raise("TAVILY_API_KEY")
        _tavily_client = TavilyClient(api_key=api_key)
    return _tavily_client


def get_weather(city: str) -> str:
    """
    通过调用 wttr.in API 查询真实天气信息。
    """
    url = f"https://wttr.in/{city}?format=j1"
    try:
        response = requests.get(url, timeout=WEATHER_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()

        current_condition = data.get("current_condition", [])
        if not current_condition:
            return "错误：天气服务未返回当前天气信息。"

        condition = current_condition[0]
        weather_desc_list = condition.get("weatherDesc", [])
        weather_desc = weather_desc_list[0].get("value", "未知") if weather_desc_list else "未知"
        temp_c = condition.get("temp_C", "未知")

        # 将结构化核心信息放在前面，便于下游工具提取与使用。
        return f"天气概况={weather_desc}; 气温C={temp_c}; 城市={city}"
    except requests.exceptions.RequestException as e:
        return f"错误：查询天气时遇到网络问题 - {e}"
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return f"错误：解析天气数据失败，可能是城市名称无效 - {e}"


def get_attraction(city: str, weather: str) -> str:
    """
    根据城市和天气，使用 Tavily Search API 搜索景点推荐。
    """
    query = f"{city} 在 {weather} 情况下值得去的旅游景点推荐及理由"
    try:
        tavily = get_tavily_client()
        response = tavily.search(query=query, search_depth="basic", include_answer=True)

        if response.get("answer"):
            return response["answer"]

        formatted_results = []
        for result in response.get("results", []):
            title = result.get("title", "无标题")
            content = result.get("content", "")
            formatted_results.append(f"- {title}: {content}")

        if not formatted_results:
            return "抱歉，没有找到相关的旅游景点推荐。"

        return "根据搜索，为您找到以下信息：\n" + "\n".join(formatted_results)
    except ValueError as e:
        return f"错误：{e}"
    except Exception as e:
        return f"错误：执行 Tavily 搜索时出现问题 - {e}"


available_tools = {
    "get_weather": get_weather,
    "get_attraction": get_attraction,
}


class OpenAICompatibleClient:
    """
    用于调用 OpenAI 兼容接口的大模型客户端。
    """

    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def generate(self, prompt: str, system_prompt: str) -> str:
        """调用 LLM 生成回应。"""
        print("正在调用大语言模型...")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
            )
            answer = response.choices[0].message.content or ""
            print("大语言模型响应成功。")
            return answer
        except Exception as e:
            print(f"调用 LLM API 时发生错误: {e}")
            return "错误：调用语言模型服务时出错。"


def truncate_single_thought_action(llm_output: str) -> str:
    """仅保留第一组 Thought/Action，避免模型一次输出多组动作。"""
    match = re.search(
        r"(Thought:.*?Action:.*?)(?=\n\s*(?:Thought:|Action:|Observation:)|\Z)",
        llm_output,
        re.DOTALL,
    )
    if not match:
        return llm_output.strip()
    return match.group(1).strip()


def parse_action(action_text: str) -> Tuple[str, str, Dict[str, str]]:
    """
    解析 Action 字段。
    返回格式：
    - ("finish", final_answer, {})
    - ("tool", tool_name, kwargs)
    - ("error", error_message, {})
    """
    action_text = action_text.strip()

    finish_match = re.fullmatch(r"Finish\[(.*)\]", action_text, re.DOTALL)
    if finish_match:
        return "finish", finish_match.group(1).strip(), {}

    tool_match = re.fullmatch(r"(\w+)\((.*)\)", action_text, re.DOTALL)
    if not tool_match:
        return "error", "Action 既不是合法工具调用，也不是 Finish[...]。", {}

    tool_name = tool_match.group(1).strip()
    args_str = tool_match.group(2).strip()
    kwargs = dict(re.findall(r'(\w+)="([^"]*)"', args_str))

    if args_str and not kwargs:
        return "error", "工具参数解析失败，请使用 arg=\"value\" 格式。", {}
    return "tool", tool_name, kwargs


def run_agent(user_prompt: str, max_steps: int = 5) -> None:
    """运行 ReAct Agent 主循环。"""
    api_key = get_env_or_raise("OPENAI_COMPAT_API_KEY")
    base_url = get_env_or_raise("OPENAI_COMPAT_BASE_URL")
    model_id = get_env_or_raise("OPENAI_COMPAT_MODEL")

    llm = OpenAICompatibleClient(
        model=model_id,
        api_key=api_key,
        base_url=base_url,
    )

    prompt_history = [f"用户请求: {user_prompt}"]
    print(f"用户输入: {user_prompt}\n" + "=" * 40)

    for i in range(max_steps):
        print(f"--- 循环 {i + 1} ---\n")
        full_prompt = "\n".join(prompt_history)
        llm_output = llm.generate(full_prompt, system_prompt=AGENT_SYSTEM_PROMPT)
        llm_output = truncate_single_thought_action(llm_output)
        print(f"模型输出:\n{llm_output}\n")
        prompt_history.append(llm_output)

        action_match = re.search(r"Action:\s*(.*)", llm_output, re.DOTALL)
        if not action_match:
            observation = "错误：未能解析到 Action 字段。请确保回复严格遵循 Thought/Action 格式。"
            observation_str = f"Observation: {observation}"
            print(f"{observation_str}\n" + "=" * 40)
            prompt_history.append(observation_str)
            continue

        action_kind, target, kwargs = parse_action(action_match.group(1))
        if action_kind == "error":
            observation_str = f"Observation: 错误：{target}"
            print(f"{observation_str}\n" + "=" * 40)
            prompt_history.append(observation_str)
            continue

        if action_kind == "finish":
            print(f"任务完成，最终答案: {target}")
            return

        tool_name = target
        if tool_name not in available_tools:
            observation = f"错误：未定义的工具 '{tool_name}'"
        else:
            try:
                observation = available_tools[tool_name](**kwargs)
            except TypeError as e:
                observation = f"错误：工具参数不匹配 - {e}"
            except Exception as e:
                observation = f"错误：工具调用失败 - {e}"

        observation_str = f"Observation: {observation}"
        print(f"{observation_str}\n" + "=" * 40)
        prompt_history.append(observation_str)

    print("达到最大循环次数，任务未完成。")


if __name__ == "__main__":
    load_dotenv()
    default_prompt = "你好，请帮我查询一下今天北京的天气，然后根据天气推荐一个合适的旅游景点。"
    user_prompt = os.getenv("USER_PROMPT", default_prompt)
    max_steps = int(os.getenv("MAX_STEPS", "5"))
    run_agent(user_prompt=user_prompt, max_steps=max_steps)