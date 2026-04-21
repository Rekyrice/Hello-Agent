import os
from typing import Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

# 加载 .env 文件中的环境变量
load_dotenv()


def get_env_or_raise(name: str) -> str:
    """读取必填环境变量，缺失时抛出异常。"""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"缺少必填环境变量：{name}")
    return value


class OpenAICompatibleClient:
    """用于调用 OpenAI 兼容接口的大模型客户端。"""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 60,
    ) -> None:
        self.model = model or get_env_or_raise("OPENAI_COMPAT_MODEL")
        resolved_api_key = api_key or get_env_or_raise("OPENAI_COMPAT_API_KEY")
        resolved_base_url = base_url or get_env_or_raise("OPENAI_COMPAT_BASE_URL")
        self.client = OpenAI(
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            timeout=timeout,
        )

    def think(self, messages: List[Dict[str, str]], temperature: float = 0) -> str:
        """按消息列表调用模型，返回文本结果。"""
        print("正在调用大语言模型...")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                stream=False,
            )
            answer = response.choices[0].message.content or ""
            print("大语言模型响应成功。")
            return answer
        except Exception as e:
            print(f"调用 LLM API 时发生错误: {e}")
            return "错误：调用语言模型服务时出错。"

    def generate(self, prompt: str, system_prompt: str) -> str:
        """按 FirstAgentTest 规范提供统一生成接口。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        return self.think(messages)


if __name__ == "__main__":
    client = OpenAICompatibleClient()
    output = client.generate(
        prompt="请给出一个快速排序的 Python 示例。",
        system_prompt="你是一个擅长 Python 的助手。",
    )
    print(output)