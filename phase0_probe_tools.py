"""Phase 0 补充探测：SDK 宿主模式下 agent 实际可用的工具列表。"""

import asyncio

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
)

REPO = "D:/github/just_for_fun"

PROMPT = """只做一件事：把你现在实际可用的全部工具名原样列出来
（你看到工具列表里有哪些，就列哪些，一条一行，不要执行任何工具）。"""


async def main():
    options = ClaudeAgentOptions(
        cwd=REPO,
        permission_mode="acceptEdits",
        max_turns=5,
    )
    client = ClaudeSDKClient(options=options)
    await client.connect(PROMPT)
    try:
        async for event in client.receive_messages():
            msg = getattr(event, "message", event)
            if isinstance(msg, SystemMessage):
                continue
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        print(b.text, flush=True)
            if isinstance(msg, ResultMessage):
                print(f"\n[turns={msg.num_turns} cost=${msg.total_cost_usd}]")
                break
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
