"""Phase 0 — galgame coding 拦截注入验证（2026-08-08）

验证两件事：
1. SDK 宿主能否在事件流里拦截到 Claude Code 的 AskUserQuestion（完整 questions 载荷）
2. 注入 tool_result 回答后，agent 是否按选择行事

顺带实测本机（Claude Code 2.1.224）的 headless 竞态行为：
   issue #50728 提到旧版本可能 ~37ms 内自动 resolve 空答案；
   v2.1.200+ 改为无人响应时挂起等待。跑一次就知道本机是哪种。
"""

import asyncio
import json

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

REPO = "D:/github/just_for_fun"

PROMPT = """在 galgame-coding/scratch 目录下创建一个小脚本（脚本内容一行 print 就行）。
但先不要动手：你必须先用 AskUserQuestion 工具问我一个问题——
脚本文件取哪个名字。给我两个选项：'alpha.py' 和 'beta.py'。
等我回答之后，再按我选的名字创建文件。"""


def describe(msg):
    """把 SDK 消息压成一行，方便追踪流程。"""
    if isinstance(msg, AssistantMessage):
        parts = []
        for b in msg.content:
            if isinstance(b, TextBlock):
                parts.append(f"text: {b.text[:80]!r}")
            elif isinstance(b, ThinkingBlock):
                parts.append("thinking…")
            elif isinstance(b, ToolUseBlock):
                parts.append(f"tool_use: {b.name}")
            elif isinstance(b, ToolResultBlock):
                parts.append("tool_result")
            else:
                parts.append(type(b).__name__)
        return f"[Assistant stop={msg.stop_reason}] " + " | ".join(parts)
    if isinstance(msg, ResultMessage):
        return (
            f"[Result err={msg.is_error} turns={msg.num_turns} cost=${msg.total_cost_usd}] "
            f"{msg.result[:120]!r}"
        )
    if isinstance(msg, SystemMessage):
        return f"[System subtype={msg.subtype}]"
    return f"[{type(msg).__name__}]"


async def main():
    options = ClaudeAgentOptions(
        cwd=REPO,
        permission_mode="acceptEdits",
        include_partial_messages=True,   # 完整 questions 载荷需要这个
        max_turns=15,
    )
    client = ClaudeSDKClient(options=options)
    await client.connect(PROMPT)

    injected = False
    n_sys = 0
    async for event in client.receive_messages():
        msg = getattr(event, "message", event)
        line = describe(msg)
        if isinstance(msg, SystemMessage):
            n_sys += 1
            if n_sys % 50 == 0:
                print(f"…（启动噪声 {n_sys} 条）", flush=True)
            continue
        print(line, flush=True)

        # ---- 拦截点：AskUserQuestion ----
        if not injected and isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, ToolUseBlock) and block.name == "AskUserQuestion":
                    print("\n=== 🎮 拦截到 AskUserQuestion ===")
                    print(json.dumps(block.input, ensure_ascii=False, indent=2))
                    questions = block.input["questions"]
                    # 注入回答：选第 2 个选项（从真实载荷里取 label，保证自洽）
                    q = questions[0]
                    label = q["options"][1]["label"]
                    answer = [{"question": q["question"], "answer": label}]
                    print(f"=== 🕹 注入回答：{label} ===", flush=True)
                    client.query(
                        UserMessage(
                            content=[
                                ToolResultBlock(
                                    tool_use_id=block.id,
                                    content=(
                                        "User has answered your questions: "
                                        + json.dumps(answer, ensure_ascii=False)
                                    ),
                                )
                            ]
                        )
                    )
                    injected = True

        if isinstance(msg, ResultMessage):
            break


if __name__ == "__main__":
    asyncio.run(main())
