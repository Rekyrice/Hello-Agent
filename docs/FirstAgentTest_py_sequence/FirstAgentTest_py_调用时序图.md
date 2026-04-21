# FirstAgentTest.py 调用时序图

```mermaid
sequenceDiagram
    title FirstAgentTest.py 调用时序图（含记忆、售罄备选、拒绝反思）

    participant IDE as VSCode/Debugpy
    participant Main as FirstAgentTest.py(__main__)
    participant User as 用户
    participant Agent as run_agent()
    participant LLMClient as OpenAICompatibleClient.generate()
    participant OpenAI as openai.OpenAI.chat.completions.create
    participant Weather as wttr.in API (requests.get)
    participant Tavily as TavilyClient.search

    IDE->>Main: 启动脚本 FirstAgentTest.py
    Main->>Main: dotenv.load_dotenv()
    Main->>Main: os.getenv(USER_PROMPT/MAX_STEPS/INTERACTIVE_MODE)
    Main->>Agent: run_agent(user_prompt, max_steps, interactive)

    Agent->>Agent: get_env_or_raise(OPENAI_COMPAT_*)
    Agent->>Agent: 创建 OpenAICompatibleClient
    Agent->>Agent: 初始化 agent_state(memory/session)
    Agent->>Agent: 从用户首轮输入抽取偏好写入 memory
    Agent->>Agent: 初始化 prompt_history

    loop 最多 max_steps 次
        Agent->>Agent: 注入系统状态(memory/session)到 full_prompt
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
            Agent->>Agent: 提取主推荐景点 primary_attraction
            Agent->>Agent: check_ticket_availability(primary_attraction)
            alt 票务状态 = sold_out
                Agent->>Tavily: search(备选 query, 排除 primary_attraction)
                Tavily-->>Agent: 备选推荐结果
                Agent-->>Agent: Observation: 原推荐售罄 + 自动备选结果
            else 票务状态 = available
                Agent-->>Agent: Observation: 景点推荐文本
            end

            alt interactive = true
                Agent->>User: 请求反馈（接受 / 拒绝：原因 / 跳过）
                User-->>Agent: 用户反馈文本
                Agent->>Agent: 更新 memory（偏好、预算）
                alt 用户反馈为拒绝
                    Agent->>Agent: rejected_count += 1
                    alt rejected_count >= 3
                        Agent->>Agent: adjust_strategy(reason)
                        Agent-->>Agent: Observation: 连续拒绝3次，策略已调整
                    end
                else 用户反馈为接受
                    Agent->>Agent: rejected_count = 0
                end
            end
        else Action = update_memory/get_memory/check_ticket_availability/get_alternative_attractions/adjust_strategy
            Agent->>Agent: 调用对应工具并更新状态
            Agent-->>Agent: Observation: 工具结果
        else Action = Finish[最终答案]
            Agent-->>Main: 任务完成，返回最终答案
            break 结束循环
        end
    end

    Main-->>IDE: 打印最终输出并退出
```

