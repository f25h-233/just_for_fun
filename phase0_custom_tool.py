"""Phase 0b — 自定义 ask_player 工具验证（2026-08-08）

AskUserQuestion 在 SDK 宿主模式不暴露（2.1.224 实测），改走自定义工具路线：
agent 调用 ask_player → 我们的 Python 函数执行（= 未来 galgame 前端入口）
→ 返回玩家选择。验证 agent 按我们的返回行事。

Phase 0 阶段无 GUI：函数里直接打印问题 + 硬编码选第 2 个选项。
"""

import asyncio

from typing import Annotated

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

REPO = "D:/github/just_for_fun"

SCHEMA = {
    "question": Annotated[str, "要问玩家的抉择问题"],
    "options": Annotated[list[str], "2-4 个候选方案，每个都带做法与代价"],
}


@tool(name="ask_player", description="向玩家提出抉择（最多 4 个选项）。", input_schema=SCHEMA)
async def ask_player(args: dict) -> dict:
    question = args["question"]
    options = args["options"]
    print(f"\n🎮 ask_player 被调用：{question}", flush=True)
    for i, opt in enumerate(options):
        print(f"   [{i}] {opt}", flush=True)
    # Phase 0 硬编码：永远选第 2 个（真实的 galgame 前端在 Phase 1 接进来）
    pick = 1
    print(f"🕹 玩家选择：[{pick}] {options[pick]}", flush=True)
    return {
        "content": [
            {"type": "text", "text": f"玩家选择了 [{pick}] {options[pick]}"}
        ]
    }


PROMPT = """在 galgame-coding/scratch 目录下创建一个小脚本（脚本内容一行 print 就行）。
先不要动手：你必须先用 ask_player 工具问我脚本文件取哪个名字，
选项给 'alpha.py' 和 'beta.py'。等我回答后，再按我选的名字创建文件。"""


async def main():
    server = create_sdk_mcp_server(name="galgame", tools=[ask_player])
    options = ClaudeAgentOptions(
        cwd=REPO,
        permission_mode="bypassPermissions",
        mcp_servers={"galgame": server},
        max_turns=15,
    )
    client = ClaudeSDKClient(options=options)
    await client.connect(PROMPT)
    try:
        async for event in client.receive_messages():
            msg = getattr(event, "message", event)
            if isinstance(msg, SystemMessage):
                continue
            if isinstance(msg, AssistantMessage):
                parts = []
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        parts.append(f"text: {b.text[:100]!r}")
                    elif isinstance(b, ThinkingBlock):
                        parts.append("thinking…")
                    elif isinstance(b, ToolUseBlock):
                        parts.append(f"tool_use: {b.name}")
                    else:
                        parts.append(type(b).__name__)
                print(f"[Assistant stop={msg.stop_reason}] " + " | ".join(parts), flush=True)
            if isinstance(msg, ResultMessage):
                print(f"[Result err={msg.is_error} turns={msg.num_turns} cost=${msg.total_cost_usd}]")
                break
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
