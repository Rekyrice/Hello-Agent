# FirstAgentTest.py 调用时序图

## 场景说明
- 目标：描述 `FirstAgentTest.py` 主循环在“调用 LLM、解析 Action、执行工具、回写 Observation、终止循环”上的完整路径。
- 关键参与者：`User`、`MainLoop`、`LLMClient`、`ToolRouter`、`WeatherAPI`、`TavilyAPI`、`Logger`。
- 当前版本变更点：`FirstAgentTest.py` 不再内嵌客户端，统一复用 `llm_client.py` 中的 `OpenAICompatibleClient`。

## 分支说明
- 成功路径：配置加载成功 -> LLM 输出可解析 -> 工具执行成功 -> `Finish` 或达到 `max_steps`。
- 异常路径：
  - 配置缺失：`OPENAI_COMPAT_*` 缺失触发 `ValueError`，流程提前终止。
  - 解析失败：未解析到 `Action` 或参数格式不合法，写入错误 Observation 后进入下一轮。
  - 网络异常：天气查询、Tavily 查询失败时返回错误 Observation，主循环继续。

```mermaid
sequenceDiagram
    title FirstAgentTest.py 调用时序图（集成 llm_client 后）

    participant User
    participant MainLoop as MainLoop(run_agent)
    participant LLMClient as LLMClient(OpenAICompatibleClient@llm_client.py)
    participant ToolRouter as ToolRouter(available_tools + parse_action)
    participant WeatherAPI as WeatherAPI(wttr.in)
    participant TavilyAPI as TavilyAPI(TavilyClient.search)
    participant Logger as Logger(print)

    User->>MainLoop: 输入旅行请求
    MainLoop->>Logger: 打印用户输入与循环开始日志
    MainLoop->>LLMClient: 初始化客户端（读取 OPENAI_COMPAT_*）

    alt 配置缺失
        LLMClient-->>MainLoop: 抛出 ValueError(缺少环境变量)
        MainLoop->>Logger: 记录并终止流程
    else 配置完整
        MainLoop->>MainLoop: 初始化状态(memory/session)与 prompt_history

        loop 直到 Finish 或 max_steps
            MainLoop->>LLMClient: generate(full_prompt, AGENT_SYSTEM_PROMPT)
            LLMClient-->>MainLoop: Thought + Action 文本
            MainLoop->>ToolRouter: truncate_single_thought_action + parse_action

            alt Action 解析失败
                ToolRouter-->>MainLoop: error(无 Action 或参数格式非法)
                MainLoop->>Logger: Observation: 错误信息
            else Action=tool(...)
                MainLoop->>ToolRouter: 路由到对应工具
                alt tool=get_weather
                    ToolRouter->>WeatherAPI: GET /{city}?format=j1
                    alt 网络或数据异常
                        WeatherAPI-->>ToolRouter: 异常
                        ToolRouter-->>MainLoop: Observation: 天气查询失败
                    else 成功
                        WeatherAPI-->>ToolRouter: 天气数据
                        ToolRouter-->>MainLoop: Observation: 天气概况
                    end
                else tool=get_attraction/get_alternative_attractions
                    ToolRouter->>TavilyAPI: search(query)
                    alt 网络异常或服务错误
                        TavilyAPI-->>ToolRouter: 异常
                        ToolRouter-->>MainLoop: Observation: 搜索失败
                    else 成功
                        TavilyAPI-->>ToolRouter: answer/results
                        ToolRouter-->>MainLoop: Observation: 景点推荐或备选
                    end
                else tool=update_memory/get_memory/check_ticket_availability/adjust_strategy
                    ToolRouter-->>MainLoop: Observation: 工具执行结果
                end
                MainLoop->>Logger: 记录 Observation 并回写 prompt_history
            else Action=Finish[final_answer]
                ToolRouter-->>MainLoop: finish(final_answer)
                MainLoop->>Logger: 打印最终答案并结束循环
                break 任务完成
            end
        end

        alt 达到 max_steps 仍未 Finish
            MainLoop->>Logger: 打印“达到最大循环次数，任务未完成”
        end
    end
```

