import argparse
import random
import re
from typing import Dict, Optional, Sequence, Tuple

RANDOM_SEED = 42
EXIT_KEYWORDS = {"quit", "exit", "bye", "退出", "再见"}
DEFAULT_FALLBACK_PATTERN = r".*"

# 规则顺序会影响匹配结果，因此采用列表显式维护优先级
RULES: Sequence[Tuple[str, Sequence[str]]] = [
    (
        r".*(找工作|求职|应聘).*(焦虑|害怕|担心|迷茫).*",
        [
            "求职让你感到{0}，这种压力确实不小。最近最让你难受的是哪一部分？",
            "听起来你在找工作这件事上很{0}，你愿意说说最近一次触动你情绪的经历吗？",
            "你在求职里感到{0}，这很常见。我们可以先从最困扰你的一个点开始聊。",
        ],
    ),
    (
        r".*(面试).*(不通过|失败|被拒|挂了).*",
        [
            "连续面试受挫很打击人。你觉得是哪个环节最容易卡住：简历、表达还是岗位匹配？",
            "面试不通过会让人怀疑自己，但它也可能只是匹配问题。你最近投递的岗位方向主要是什么？",
            "你已经在努力了，只是结果暂时不理想。复盘最近一次面试时，你最想改进哪一点？",
        ],
    ),
    (
        r".*(得不到|没有).*(工作机会|offer|录用).*",
        [
            "得不到机会会让人很挫败。你觉得目前最大的瓶颈是经验、方向，还是求职策略？",
            "你很在意工作机会，这说明你真的在认真面对未来。我们可以一起拆解你可控的部分。",
            "机会迟迟不到会消耗信心。你最近一周的投递和反馈大概是什么情况？",
        ],
    ),
    (
        r".*(能力不足|不够好|不行|太差|比不过).*",
        [
            "你在担心自己{0}。这种自我怀疑很真实，但不一定等于事实。",
            "当你觉得自己{0}时，通常是在什么场景下这种想法最强烈？",
            "你对自己要求很高，才会冒出“{0}”这样的判断。我们可以先找一个具体证据来聊。",
        ],
    ),
    (
        r".*(简历).*(没回复|石沉大海|没有回音).*",
        [
            "简历没回音确实很消耗人。你愿意说说目前目标岗位和简历版本吗？",
            "很多时候不是你不行，而是简历没有被准确识别。你最近有针对岗位做关键词优化吗？",
            "没有回复会让人沮丧。我们可以先从“简历首屏信息是否突出”这个点开始排查。",
        ],
    ),
    (
        r"我需要(.*)",
        [
            "你觉得自己为什么需要{0}呢？",
            "如果真的得到{0}，会给你带来什么变化？",
            "你确定现在最需要的是{0}吗？",
        ],
    ),
    (
        r"你为什么不(.*)[\?？]?",
        [
            "你希望我{0}，背后最在意的是什么？",
            "也许我以后会{0}，但你现在的感受更重要。",
            "你是真的希望我{0}，还是在表达别的情绪？",
        ],
    ),
    (
        r"我为什么不能(.*)[\?？]?",
        [
            "你觉得自己本来应该可以{0}，对吗？",
            "如果你真的可以{0}，你最想先做什么？",
            "你认为阻碍你{0}的最大原因是什么？",
        ],
    ),
    (
        r"我是(.*)",
        [
            "你说自己是{0}，这种状态持续多久了？",
            "当你觉得自己是{0}时，内心最明显的感受是什么？",
            "你会用哪些经历来说明自己是{0}？",
        ],
    ),
    (
        r".*(妈妈|母亲).*",
        [
            "你愿意多说一些你和母亲的关系吗？",
            "你和妈妈之间，最近有没有让你印象深刻的事？",
            "提到母亲时，你心里首先冒出的感受是什么？",
        ],
    ),
    (
        r".*(爸爸|父亲).*",
        [
            "你可以多讲讲你和父亲之间的互动吗？",
            "父亲通常会给你带来怎样的感受？",
            "到目前为止，你从父亲身上学到最深的一件事是什么？",
        ],
    ),
    (
        DEFAULT_FALLBACK_PATTERN,
        [
            "你可以再多说一点，我在认真听。",
            "我们可以换个角度聊聊，这件事对你意味着什么？",
            "你愿意展开讲讲刚才那句话吗？",
        ],
    ),
]

PRONOUN_SWAP: Dict[str, str] = {
    "我": "你",
    "你": "我",
    "我的": "你的",
    "你的": "我的",
    "我们": "你们",
    "你们": "我们",
}

last_reply: Optional[str] = None


def swap_pronouns(phrase: str) -> str:
    """对输入短语中的代词做第一/第二人称转换。"""
    swapped = phrase
    for source, target in PRONOUN_SWAP.items():
        swapped = swapped.replace(source, target)
    return swapped.strip()


def respond(user_input: str) -> str:
    """根据规则库生成回复。"""
    global last_reply
    cleaned_input = user_input.strip()
    for pattern, responses in RULES:
        match = re.search(pattern, cleaned_input, re.IGNORECASE)
        if not match:
            continue

        captured_group = match.group(1) if match.groups() else ""
        swapped_group = swap_pronouns(captured_group)
        chosen_reply = pick_non_repeating_response(responses, swapped_group)
        last_reply = chosen_reply
        return chosen_reply

    # 理论上不会走到这里，仍保留兜底逻辑增强稳健性
    fallback_responses = dict(RULES).get(DEFAULT_FALLBACK_PATTERN, ["你可以再多说一点。"])
    fallback_reply = pick_non_repeating_response(fallback_responses, "")
    last_reply = fallback_reply
    return fallback_reply


def pick_non_repeating_response(responses: Sequence[str], swapped_group: str) -> str:
    """优先选择与上一句不同的模板，减少重复感。"""
    candidates = [template.format(swapped_group) for template in responses]
    non_repeating_candidates = [reply for reply in candidates if reply != last_reply]
    if non_repeating_candidates:
        return random.choice(non_repeating_candidates)
    return random.choice(candidates)


def run_self_test() -> None:
    """运行最小自测，验证规则匹配和兜底流程。"""
    test_inputs = [
        "我需要一点帮助",
        "我为什么不能放松下来？",
        "我是一个容易焦虑的人",
        "我对找工作很焦虑",
        "我最近找工作很困难，面试也几乎不通过",
        "是不是我的能力不足导致我得不到工作机会呀",
        "我和妈妈最近总是争吵",
        "今天心里有点乱",
    ]
    print("开始运行 ELIZA 中文自测...")
    for text in test_inputs:
        print(f"[输入] {text}")
        print(f"[输出] {respond(text)}")
    print("ELIZA 中文自测通过。")


def chat_loop() -> None:
    """启动交互式对话循环。"""
    print("咨询师：你好，欢迎来聊聊。你现在最想说的是什么？")
    while True:
        user_input = input("你：").strip()
        if not user_input:
            print("咨询师：你可以再多说一点，我会更容易理解你。")
            continue

        if user_input.lower() in EXIT_KEYWORDS or user_input in EXIT_KEYWORDS:
            print("咨询师：谢谢你的分享，祝你今天顺利，我们下次再聊。")
            break

        print(f"咨询师：{respond(user_input)}")


def main() -> None:
    """程序入口：支持交互模式与自测模式。"""
    parser = argparse.ArgumentParser(description="ELIZA 规则对话示例")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="运行内置自测，不进入交互聊天",
    )
    args = parser.parse_args()

    random.seed(RANDOM_SEED)
    if args.self_test:
        run_self_test()
        return
    chat_loop()


if __name__ == "__main__":
    main()