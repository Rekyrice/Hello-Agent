# FirstAgentTest.py 调用时序图

```mermaid
sequenceDiagram
    title FirstAgentTest.py 调用时序图（点击运行到最终输出）

    participant IDE as VSCode/Debugpy
    participant Main as FirstAgentTest.py(__main__)
    participant Agent as run_agent()
    participant LLMClient as OpenAICompatibleClient.generate()
    participant OpenAI as openai.OpenAI.chat.completions.create
    participant Weather as wttr.in API (requests.get)
    participant Tavily as TavilyClient.search

    IDE->>Main: 启动脚本 FirstAgentTest.py
    Main->>Main: dotenv.load_dotenv()
    Main->>Main: os.getenv(USER_PROMPT/MAX_STEPS)
    Main->>Agent: run_agent(user_prompt, max_steps)

    Agent->>Agent: get_env_or_raise(OPENAI_COMPAT_*)
    Agent->>Agent: 创建 OpenAICompatibleClient
    Agent->>Agent: 初始化 prompt_history

    loop 最多 max_steps 次
        Agent->>LLMClient: generate(full_prompt, AGENT_SYSTEM_PROMPT)
        LLMClient->>OpenAI: chat.completions.create(model, messages)
        OpenAI-->>LLMClient: Thought + Action 文本
        LLMClient-->>Agent: llm_output
        Agent->>Agent: truncate_single_thought_action()
        Agent->>Agent: parse_action()

        alt Action = get_weather(city="北京")
            Agent->>Weather: requests.get("https://wttr.in/北京?format=j1", timeout=12)
            Weather-->>Agent: 天气 JSON
            Agent->>Agent: 提取 weatherDesc/temp_C
            Agent-->>Agent: Observation: 天气概况=Clear; 气温C=21; 城市=北京
        else Action = get_attraction(city="北京", weather="Clear")
            Agent->>Agent: get_tavily_client()（懒加载/复用）
            Agent->>Tavily: search(query, search_depth="basic", include_answer=True)
            Tavily-->>Agent: answer/results
            Agent-->>Agent: Observation: 景点推荐文本
        else Action = Finish[最终答案]
            Agent-->>Main: 任务完成，返回最终答案
            break 结束循环
        end
    end

    Main-->>IDE: 打印最终输出并退出
```

