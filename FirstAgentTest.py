import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from openai import OpenAI
from tavily import TavilyClient

AGENT_SYSTEM_PROMPT = """
你是一个智能旅行助手。你的任务是分析用户的请求，并使用可用工具一步步地解决问题。

# 可用工具:
- `get_weather(city: str)`: 查询指定城市的实时天气。
- `get_attraction(city: str, weather: str)`: 根据城市和天气搜索推荐的旅游景点。
- `update_memory(key: str, value: str)`: 更新用户偏好记忆（如 liked_types、budget_max）。
- `get_memory()`: 读取当前用户偏好记忆。
- `check_ticket_availability(attraction: str)`: 检查景点门票是否售罄。
- `get_alternative_attractions(city: str, weather: str, exclude: str)`: 当景点售罄时获取备选方案。
- `adjust_strategy(reason: str)`: 当用户连续拒绝推荐时，调整推荐策略。

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
- 推荐景点前必须结合系统状态中的 memory 与 strategy
- 推荐后若收到售罄 Observation，应优先调用备选景点工具
- 如果系统提示用户已连续拒绝3次，必须先调用 adjust_strategy 再继续推荐

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
    """通过调用 wttr.in API 查询真实天气信息。"""
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

        return f"天气概况={weather_desc}; 气温C={temp_c}; 城市={city}"
    except requests.exceptions.RequestException as e:
        return f"错误：查询天气时遇到网络问题 - {e}"
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return f"错误：解析天气数据失败，可能是城市名称无效 - {e}"


def get_attraction(city: str, weather: str) -> str:
    """根据城市和天气，使用 Tavily Search API 搜索景点推荐。"""
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


def build_initial_agent_state() -> Dict[str, Any]:
    """初始化智能体状态。"""
    return {
        "memory": {
            "liked_types": [],
            "disliked_types": [],
            "budget_max": "",
        },
        "session": {
            "rejected_count": 0,
            "strategy": "preference_first",
            "last_city": "",
            "last_weather": "",
            "last_recommendations": [],
        },
    }


def deduplicate_preserve_order(items: List[str]) -> List[str]:
    """按原顺序去重。"""
    seen = set()
    result = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def split_preference_values(raw_value: str) -> List[str]:
    """将逗号、顿号、斜杠分隔的偏好字符串拆分为列表。"""
    return deduplicate_preserve_order(re.split(r"[,，、/;；\s]+", raw_value.strip()))


def extract_preferences_from_text(text: str) -> Dict[str, List[str]]:
    """从文本中提取偏好关键词。"""
    lower_text = text.lower()
    liked_candidates: List[str] = []
    disliked_candidates: List[str] = []

    has_negative = any(k in text for k in ["不喜欢", "不要", "拒绝", "不想", "别"])

    if any(k in text for k in ["历史", "文化", "博物馆", "古迹"]):
        if has_negative:
            disliked_candidates.append("历史文化")
        else:
            liked_candidates.append("历史文化")
    if any(k in text for k in ["现代", "建筑", "商圈", "城市地标"]):
        liked_candidates.append("现代建筑")
    if any(k in text for k in ["长城", "故宫", "国博"]) and has_negative:
        disliked_candidates.append("历史文化")
    if any(k in text for k in ["游乐场", "刺激项目"]) and has_negative:
        disliked_candidates.append("游乐场")
    if any(k in text for k in ["热门", "人多"]) and has_negative:
        disliked_candidates.append("热门拥挤")

    if any(k in text for k in ["自然", "公园", "山", "湖"]):
        liked_candidates.append("自然风光")
    if any(k in text for k in ["人少", "小众", "安静"]):
        liked_candidates.append("小众安静")
    if "太贵" in text or "预算" in text or "cost" in lower_text:
        liked_candidates.append("高性价比")

    budget_matches = re.findall(r"预算[^0-9]{0,5}(\d+)|(\d+)\s*元", text)
    budget_values = [a or b for a, b in budget_matches if (a or b)]

    return {
        "liked": deduplicate_preserve_order(liked_candidates),
        "disliked": deduplicate_preserve_order(disliked_candidates),
        "budget_values": budget_values,
    }


def update_memory_from_text(state: Dict[str, Any], text: str) -> None:
    """根据用户输入或反馈更新偏好记忆。"""
    extracted = extract_preferences_from_text(text)
    memory = state["memory"]
    memory["liked_types"] = deduplicate_preserve_order(memory["liked_types"] + extracted["liked"])
    memory["disliked_types"] = deduplicate_preserve_order(
        memory["disliked_types"] + extracted["disliked"]
    )
    if extracted["budget_values"]:
        memory["budget_max"] = extracted["budget_values"][-1]
    memory["liked_types"] = [
        item for item in memory["liked_types"] if item not in set(memory["disliked_types"])
    ]


def update_memory(key: str, value: str) -> str:
    """占位工具：实际状态更新由主循环处理。"""
    return f"已记录记忆更新请求：{key}={value}"


def get_memory() -> str:
    """占位工具：真实记忆由主循环注入 Prompt。"""
    return "记忆由系统状态管理，请查看系统状态。"


def check_ticket_availability(attraction: str) -> str:
    """MVP：用规则模拟票务状态，后续可替换为真实票务接口。"""
    sold_out_keywords = ["故宫", "国博", "热门"]
    if any(keyword in attraction for keyword in sold_out_keywords):
        return f"景点={attraction}; 票务状态=sold_out; 建议=推荐备选方案"
    return f"景点={attraction}; 票务状态=available; 建议=可继续推荐"


def get_alternative_attractions(
    city: str,
    weather: str,
    exclude: str,
    preferred: str = "",
    disliked: str = "",
    budget_max: str = "",
    strategy: str = "",
) -> str:
    """根据城市、天气和排除景点获取备选推荐。"""
    preferred_clause = f"偏好 {preferred}，" if preferred else ""
    disliked_clause = f"避开 {disliked} 类型，" if disliked else ""
    budget_clause = f"预算不超过 {budget_max} 元，" if budget_max else ""
    strategy_clause = f"策略={strategy}，" if strategy else ""
    hard_exclusion_clause = (
        "严禁推荐历史文化类景点（如故宫、长城、天坛、明十三陵、王府、古迹、博物馆），"
        if "历史文化" in disliked
        else ""
    )
    query = (
        f"{city} 在 {weather} 情况下适合游览的备选景点，"
        f"排除 {exclude}，{preferred_clause}{disliked_clause}{budget_clause}{strategy_clause}"
        f"{hard_exclusion_clause}请仅返回中文结果，并给出简短理由"
    )

    forbidden_keywords = ["故宫", "长城", "天坛", "明十三陵", "恭王府", "古迹", "博物馆"]

    def _contains_forbidden(text: str) -> bool:
        if "历史文化" not in disliked:
            return False
        return any(keyword in text for keyword in forbidden_keywords)

    try:
        tavily = get_tavily_client()
        response = tavily.search(query=query, search_depth="basic", include_answer=True)
        answer = response.get("answer", "")
        if answer and not _contains_forbidden(answer):
            return f"备选推荐：{answer}"
        if answer and _contains_forbidden(answer):
            retry_query = (
                query
                + "。再次强调：不要出现任何历史文化景点名称；请推荐现代建筑、自然公园、商业休闲类。"
            )
            retry_response = tavily.search(
                query=retry_query,
                search_depth="basic",
                include_answer=True,
            )
            retry_answer = retry_response.get("answer", "")
            if retry_answer and not _contains_forbidden(retry_answer):
                return f"备选推荐：{retry_answer}"
            return (
                "备选推荐：可考虑奥林匹克公园、798艺术区、朝阳公园。"
                "这些景点更偏现代、休闲与户外体验。"
            )

        fallback_results = []
        for result in response.get("results", [])[:3]:
            title = result.get("title", "无标题")
            content = result.get("content", "")
            fallback_results.append(f"- {title}: {content}")
        if fallback_results:
            return "备选推荐如下：\n" + "\n".join(fallback_results)
        return "备选推荐：未检索到理想结果，请尝试调整偏好。"
    except Exception as e:
        return f"错误：获取备选景点失败 - {e}"


def adjust_strategy(reason: str) -> str:
    """根据拒绝原因调整策略。"""
    negative_context = any(k in reason for k in ["拒绝", "不想", "不要", "不喜欢", "避开"])
    if negative_context and any(k in reason for k in ["历史", "文化"]):
        return "策略已调整为 natural_modern_first（自然与现代优先）"
    if "贵" in reason or "预算" in reason:
        return "策略已调整为 budget_first（预算优先）"
    if "人多" in reason or "热门" in reason:
        return "策略已调整为 niche_first（小众优先）"
    if "历史" in reason or "文化" in reason:
        return "策略已调整为 culture_first（历史文化优先）"
    return "策略已调整为 mixed_refine（综合偏好精细化）"


def extract_primary_attraction(text: str) -> Optional[str]:
    """从推荐文本中提取主推荐景点名。"""
    bullet_match = re.search(r"-\s*([^:：\n]+)\s*[:：]", text)
    if bullet_match:
        return bullet_match.group(1).strip()
    named_match = re.search(r"(推荐|建议).{0,8}去([^，。；\n]+)", text)
    if named_match:
        return named_match.group(2).strip()
    scenic_match = re.search(r"是([^，。；\n]+)", text)
    if scenic_match:
        first_segment = scenic_match.group(1).strip()
        first_item = re.split(r"[和、,，及]", first_segment)[0].strip()
        if first_item:
            return first_item
    return None


def is_rejection_feedback(text: str) -> bool:
    """识别用户是否在表达拒绝意图。"""
    rejection_keywords = ["拒绝", "不喜欢", "不要", "不想", "太贵", "不合适", "换一个", "再换"]
    return any(keyword in text for keyword in rejection_keywords)


def collect_user_feedback() -> str:
    """交互式收集用户反馈。"""
    return input("请输入反馈（接受 / 拒绝：原因 / 跳过）：").strip()


available_tools = {
    "get_weather": get_weather,
    "get_attraction": get_attraction,
    "update_memory": update_memory,
    "get_memory": get_memory,
    "check_ticket_availability": check_ticket_availability,
    "get_alternative_attractions": get_alternative_attractions,
    "adjust_strategy": adjust_strategy,
}


class OpenAICompatibleClient:
    """用于调用 OpenAI 兼容接口的大模型客户端。"""

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


def run_agent(user_prompt: str, max_steps: int = 8, interactive: bool = True) -> None:
    """运行 ReAct Agent 主循环。"""
    api_key = get_env_or_raise("OPENAI_COMPAT_API_KEY")
    base_url = get_env_or_raise("OPENAI_COMPAT_BASE_URL")
    model_id = get_env_or_raise("OPENAI_COMPAT_MODEL")

    llm = OpenAICompatibleClient(
        model=model_id,
        api_key=api_key,
        base_url=base_url,
    )

    agent_state = build_initial_agent_state()
    update_memory_from_text(agent_state, user_prompt)

    prompt_history = [f"用户请求: {user_prompt}"]
    print(f"用户输入: {user_prompt}\n" + "=" * 40)

    for i in range(max_steps):
        print(f"--- 循环 {i + 1} ---\n")
        state_snapshot = (
            "系统状态:\n"
            f"- memory={agent_state['memory']}\n"
            f"- session={agent_state['session']}"
        )
        full_prompt = "\n".join(prompt_history + [state_snapshot])
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
                if tool_name == "update_memory":
                    key = kwargs.get("key", "").strip()
                    value = kwargs.get("value", "").strip()
                    if key and value and key in agent_state["memory"]:
                        if key in ["liked_types", "disliked_types"]:
                            current = agent_state["memory"][key]
                            current.extend(split_preference_values(value))
                            agent_state["memory"][key] = deduplicate_preserve_order(current)
                        else:
                            agent_state["memory"][key] = value
                        observation = f"记忆更新成功：{key}={agent_state['memory'][key]}"
                    else:
                        observation = available_tools[tool_name](**kwargs)
                elif tool_name == "get_memory":
                    observation = f"当前记忆：{agent_state['memory']}"
                elif tool_name == "adjust_strategy":
                    observation = available_tools[tool_name](**kwargs)
                    if "budget_first" in observation:
                        agent_state["session"]["strategy"] = "budget_first"
                    elif "niche_first" in observation:
                        agent_state["session"]["strategy"] = "niche_first"
                    elif "culture_first" in observation:
                        agent_state["session"]["strategy"] = "culture_first"
                    else:
                        agent_state["session"]["strategy"] = "mixed_refine"
                else:
                    observation = available_tools[tool_name](**kwargs)
            except TypeError as e:
                observation = f"错误：工具参数不匹配 - {e}"
            except Exception as e:
                observation = f"错误：工具调用失败 - {e}"

        if tool_name == "get_attraction":
            agent_state["session"]["last_city"] = kwargs.get("city", "")
            agent_state["session"]["last_weather"] = kwargs.get("weather", "")

            primary_attraction = extract_primary_attraction(observation)
            if primary_attraction:
                agent_state["session"]["last_recommendations"] = [primary_attraction]
                availability = check_ticket_availability(primary_attraction)
                availability_observation = f"Observation: {availability}"
                print(f"{availability_observation}\n" + "=" * 40)
                prompt_history.append(availability_observation)

                if "sold_out" in availability:
                    alternative = get_alternative_attractions(
                        city=agent_state["session"]["last_city"] or "本地",
                        weather=agent_state["session"]["last_weather"] or "未知天气",
                        exclude=primary_attraction,
                        preferred=",".join(agent_state["memory"]["liked_types"]),
                        disliked=",".join(agent_state["memory"]["disliked_types"]),
                        budget_max=agent_state["memory"]["budget_max"],
                        strategy=agent_state["session"]["strategy"],
                    )
                    observation = (
                        f"{observation}\n\n原推荐景点 {primary_attraction} 已售罄，已自动切换备选：\n{alternative}"
                    )

        elif tool_name == "get_alternative_attractions":
            kwargs_with_context = {
                "city": kwargs.get("city", agent_state["session"]["last_city"] or "本地"),
                "weather": kwargs.get("weather", agent_state["session"]["last_weather"] or "未知天气"),
                "exclude": kwargs.get("exclude", ""),
                "preferred": ",".join(agent_state["memory"]["liked_types"]),
                "disliked": ",".join(agent_state["memory"]["disliked_types"]),
                "budget_max": agent_state["memory"]["budget_max"],
                "strategy": agent_state["session"]["strategy"],
            }
            try:
                observation = get_alternative_attractions(**kwargs_with_context)
            except Exception as e:
                observation = f"错误：获取备选景点失败 - {e}"

        observation_str = f"Observation: {observation}"
        print(f"{observation_str}\n" + "=" * 40)
        prompt_history.append(observation_str)

        if interactive and tool_name in ["get_attraction", "get_alternative_attractions"]:
            user_feedback = collect_user_feedback()
            if user_feedback and user_feedback != "跳过":
                feedback_str = f"用户反馈: {user_feedback}"
                print(feedback_str + "\n" + "=" * 40)
                prompt_history.append(feedback_str)
                update_memory_from_text(agent_state, user_feedback)

                if is_rejection_feedback(user_feedback):
                    agent_state["session"]["rejected_count"] += 1
                    if agent_state["session"]["rejected_count"] >= 3:
                        strategy_result = adjust_strategy(user_feedback)
                        if "natural_modern_first" in strategy_result:
                            agent_state["session"]["strategy"] = "natural_modern_first"
                        elif "budget_first" in strategy_result:
                            agent_state["session"]["strategy"] = "budget_first"
                        elif "niche_first" in strategy_result:
                            agent_state["session"]["strategy"] = "niche_first"
                        elif "culture_first" in strategy_result:
                            agent_state["session"]["strategy"] = "culture_first"
                        else:
                            agent_state["session"]["strategy"] = "mixed_refine"
                        force_reflect = (
                            f"Observation: 用户已连续拒绝3次。{strategy_result}，请据此调整下一轮推荐。"
                        )
                        print(force_reflect + "\n" + "=" * 40)
                        prompt_history.append(force_reflect)
                elif "接受" in user_feedback:
                    agent_state["session"]["rejected_count"] = 0
                    print("任务完成，最终答案: 已根据你的反馈确认当前推荐方案，祝你旅途愉快！")
                    return

    print("达到最大循环次数，任务未完成。")


if __name__ == "__main__":
    load_dotenv()
    default_prompt = "你好，请帮我查询一下今天北京的天气，然后根据天气推荐一个合适的旅游景点。"
    user_prompt = os.getenv("USER_PROMPT", default_prompt)
    max_steps = int(os.getenv("MAX_STEPS", "8"))
    interactive = os.getenv("INTERACTIVE_MODE", "true").lower() == "true"
    run_agent(user_prompt=user_prompt, max_steps=max_steps, interactive=interactive)