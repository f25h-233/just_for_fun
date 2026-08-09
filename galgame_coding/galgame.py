"""宿主核心：装配 MCP server、跑消息循环。

从 phase0_custom_tool.py 演进：ask_player 不再是硬编码 pick，
而是调用前端（Phase 1 = 终端菜单）等待玩家真实输入。

Phase 3 回档：SDK 会话内无法回退，回档 = 切断当前会话 + 用重建的
任务描述（已确定剧情摘要 + 回档指令）重启新会话。run() 是外层循环，
run_session() 是单次会话；回档点由工具层经 _QuitSignal.rollback 传出。
"""

import asyncio

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
)

from .characters import Cast
from .frontends.terminal import TerminalFrontend
from .history import History
from .prompt import build_prompt
from .story import StoryMemory
from .style import Style
from .tools import make_ask_player

REPO = "D:/github/just_for_fun"
MAX_TURNS = 90  # Phase 3.1：五章大任务需要更多轮次（15 会被提前截断；60 仍不够——
                # 2026-08-09 live 实测 61 轮 err=True 截断在第 5 章中段，77 轮才完成过）


class _QuitSignal:
    """会话切断信号：工具层置位，宿主循环在下一个事件到达时切断会话。

    rollback 非 None = 玩家回档到该轮（回档也是切断会话，同时置
    requested=True）；宿主先判 rollback 再判纯退出。
    """

    def __init__(self) -> None:
        self.requested = False
        self.rollback: int | None = None

    def signal(self) -> None:
        self.requested = True

    def signal_rollback(self, round: int) -> None:
        self.rollback = round
        self.requested = True


def _summarize(msg: AssistantMessage) -> str:
    """把 AssistantMessage 压成单行摘要（承自 phase0_intercept.py 的思路）。"""
    parts = []
    for b in msg.content:
        if isinstance(b, TextBlock):
            parts.append(f"text: {b.text[:80]!r}")
        elif isinstance(b, ThinkingBlock):
            parts.append("thinking…")
        elif isinstance(b, ToolUseBlock):
            args = str(b.input)[:60] if b.input else ""
            parts.append(f"tool_use: {b.name}{args}")
        else:
            parts.append(type(b).__name__)
    return f"[Assistant stop={msg.stop_reason}] " + " | ".join(parts)


async def run(
    task: str | None,
    light_novel: bool = False,
    style: Style | None = None,
    reset_cast: bool = False,
) -> None:
    """发起 galgame 会话（外层循环：支持回档重启）。

    回档流程：会话内玩家回档 → 工具层截断历史并置信号 → run_session
    返回回档轮号 → 用 history.describe() 重建任务描述（已确定剧情 +
    回档指令）→ 重启新会话。无回档则结束。

    light_novel=True 时用提示词凑合版日轻化（宿主侧改写照常，但角色
    档案只读不更新）；style 指定文风；reset_cast 先清空角色档案
    （新周目/换角色）。回档不改 cast（角色记得之前的分支）。
    """
    if reset_cast:
        Cast.reset()
    cast = Cast.load()
    history = History()
    story = StoryMemory()  # Phase 3.2 剧情记忆（会话级，与 History 同级）
    current_task = build_prompt(task, light_novel=light_novel)
    while True:
        rollback_at = await run_session(
            current_task,
            light_novel=light_novel,
            style=style,
            cast=cast,
            history=history,
            story=story,
        )
        if rollback_at is None:
            break
        print(f"⏪ 回档到第 {rollback_at} 轮，剧情从该点重新分叉…", flush=True)
        # 重建任务：已确定剧情（截断后的 1..n-1 轮）+ 回档指令追加在任务之后
        current_task = build_prompt(
            task,
            light_novel=light_novel,
            established=history.describe(),
            rollback_at=rollback_at,
        )


async def run_session(
    prompt: str,
    *,
    light_novel: bool,
    style: Style | None,
    cast: Cast,
    history: History,
    story: StoryMemory,
) -> int | None:
    """单次会话：注入 prompt，循环收消息直到结果或玩家退出/回档。

    返回回档目标轮号（玩家回档切断会话），否则 None。
    """
    quit_signal = _QuitSignal()
    server = create_sdk_mcp_server(
        name="galgame",
        tools=[make_ask_player(
            TerminalFrontend(), quit_signal.signal,
            style=style, cast=cast, read_only=light_novel,
            history=history, rollback_signal=quit_signal.signal_rollback,
            story=story,
        )],
    )
    options = ClaudeAgentOptions(
        cwd=REPO,
        permission_mode="bypassPermissions",  # acceptEdits 会拒绝 MCP 工具调用
        mcp_servers={"galgame": server},
        max_turns=MAX_TURNS,
    )
    client = ClaudeSDKClient(options=options)
    await client.connect(prompt)
    rollback_at: int | None = None
    try:
        async for event in client.receive_messages():
            if quit_signal.rollback is not None:
                rollback_at = quit_signal.rollback
                print(f"⏪ 玩家回档到第 {rollback_at} 轮，切断会话。", flush=True)
                break
            if quit_signal.requested:
                print("🚪 玩家已退出，切断会话。", flush=True)
                break
            msg = getattr(event, "message", event)
            if isinstance(msg, SystemMessage):
                continue
            if isinstance(msg, AssistantMessage):
                print(_summarize(msg), flush=True)
            if isinstance(msg, ResultMessage):
                print(
                    f"[Result err={msg.is_error} turns={msg.num_turns} "
                    f"cost=${msg.total_cost_usd}]",
                    flush=True,
                )
                break
    finally:
        if not light_novel:
            cast.save()  # 兜底保存（编剧已按轮保存；此处覆盖 ask 期间 Ctrl+C）
        await client.disconnect()
    return rollback_at
