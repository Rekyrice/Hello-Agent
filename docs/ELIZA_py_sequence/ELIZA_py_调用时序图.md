# ELIZA.py 调用时序图

## 场景说明
- 目标模块：`ELIZA.py`
- 场景覆盖：启动初始化、参数分支（自测/交互）、规则匹配、兜底回复、退出流程
- 参与者（按需）：`User`、`MainLoop`、`Logger`

## 分支说明
- `alt` 自测模式：执行内置样例并输出结果后结束
- `else` 交互模式：循环读取输入，按退出/空输入/正常输入分别处理
- 规则匹配分支：命中特定正则时生成模板回复；否则走通配符兜底

```mermaid
sequenceDiagram
    title ELIZA.py 调用时序图（含自测与交互分支）

    participant User as User
    participant MainLoop as MainLoop(ELIZA.py)
    participant Logger as Logger(stdout)

    User->>MainLoop: 启动脚本 python ELIZA.py [--self-test]
    MainLoop->>MainLoop: main() 解析 argparse 参数
    MainLoop->>MainLoop: random.seed(RANDOM_SEED)

    alt 参数为 --self-test
        MainLoop->>Logger: 输出“开始运行 ELIZA 自测...”
        loop 遍历 test_inputs
            MainLoop->>MainLoop: respond(text)
            MainLoop->>MainLoop: 按 RULES 顺序执行正则匹配
            alt 命中规则（如 I need / Why can't I / I am）
                MainLoop->>MainLoop: 提取捕获组 -> swap_pronouns()
                MainLoop->>MainLoop: random.choice(模板) + format()
                MainLoop-->>Logger: 输出 [输入]/[输出]
            else 未命中特定规则
                MainLoop->>MainLoop: 使用 DEFAULT_FALLBACK_PATTERN 兜底回复
                MainLoop-->>Logger: 输出兜底回复
            end
        end
        MainLoop->>Logger: 输出“ELIZA 自测通过。”
        MainLoop-->>User: 进程结束
    else 交互模式
        MainLoop->>Logger: 输出欢迎语
        loop 持续对话循环
            User->>MainLoop: 输入文本
            alt 输入为空
                MainLoop-->>Logger: 提示“请提供更多信息”
            else 输入为 quit/exit/bye
                MainLoop-->>Logger: 输出告别语
                MainLoop-->>User: break，结束循环
            else 正常输入
                MainLoop->>MainLoop: respond(user_input)
                MainLoop->>MainLoop: 规则匹配 + 代词转换 + 模板生成
                MainLoop-->>Logger: 输出 Therapist 回复
            end
        end
    end
```

## 维护建议
- 若新增规则模式，需同步更新“规则匹配分支”中的说明与 Mermaid 片段。
- 若新增配置加载、外部 API 或日志组件，建议补充对应参与者与异常分支。
