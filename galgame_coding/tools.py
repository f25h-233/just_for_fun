"""ask_player 工具定义：宿主与 agent 之间的抉择通道。

Phase 0 硬编码 pick=1 的函数体，换成真实前端等待玩家输入。
返回契约不变：MCP 风格 {"content": [{"type": "text", ...}]}，
且只告诉 agent 玩家选了哪个——不夹带任何新信息。

Phase 2 起：玩家侧渲染的载荷先经 novelize_payload 改写（nonce
占位符方案），agent 侧返回值仍用原文——改写对 agent 完全透明。

Phase 2.1 时序（Plan agent 审查定稿——编剧延迟被玩家阅读时间隐藏，
两条降级链不叠加在关键路径上）：

    novelize（解释器，120s）→ note_appearance + 打印🎭登场角色
    → frontend.ask()（玩家阅读+抉择）
    → 玩家选择后：call_editor（编剧，60s）→ update_from_editor
    → cast.save() → 工具返回

PlayerQuit/Ctrl+C 跳过编剧（best-effort，角色下次出现再立档）。
read_only=True（--novel-lite）时 cast 参与掩码/回填但禁编剧与保存。

Phase 3 回档：玩家在 ask 时输入 r → 前端抛 RollbackRequest(n) →
工具层截断历史（truncate 到 n-1）、置回档信号、返回收尾文本
（与 PlayerQuit 同路径，**不跑编剧**——旧分支的角色更新不进新档案）。
正常路径在 ask 之后 history.record 双存（原文=agent 侧、改写=玩家侧）。

Phase 3.2 剧情记忆联动：每轮开头 story.begin_round（含降级轮——
占号保轮号对齐）；回档路径 story.truncate(n-1) 与 history 同截断
（按轮号过滤 + 恢复分支点的上一幕，见 story.py docstring）。
"""

from typing import Annotated, Callable

from claude_agent_sdk import tool

from .characters import Cast
from .editor import call_editor
from .frontend import Frontend, PlayerQuit, RollbackRequest
from .history import History
from .novel import novelize_payload
from .story import StoryMemory
from .style import Style, get_style

SCHEMA = {
    "question": Annotated[str, "要问玩家的抉择问题"],
    "options": Annotated[
        list[dict],
        "2-4 个选项，每个 dict 含：label（10 字内的短名，如'方案B：SQLite存储'）；"
        "detail（完整描述，必须含【做法】【代价】【回滚】三要素）",
    ],
}


def make_ask_player(
    frontend: Frontend,
    quit_signal: Callable[[], None],
    *,
    style: Style | None = None,
    cast: Cast | None = None,
    read_only: bool = False,
    history: History | None = None,
    rollback_signal: Callable[[int], None] | None = None,
    story: StoryMemory | None = None,
):
    """构造 ask_player 工具。

    frontend: 渲染 + 等待玩家输入；quit_signal: 玩家退出时置位，
    宿主循环据此切断会话（agent 不该收到 MCP 报错后困惑地重试）。
    style/cast: Phase 2.1 —— 文风与角色档案；read_only 禁编剧与保存。
    history/rollback_signal: Phase 3 回档 —— 抉择记录（双存原文+改写）
    与回档信号（宿主据此切断会话并重启）；缺省时回档退化为退出。
    story: Phase 3.2 剧情记忆 —— 解释器改写时注入前情/上一幕（novelize
    内部记账 summary），玩家选择后宿主 record_scene 更新上一幕；
    每轮 begin_round 占号，回档路径 story.truncate 与 history 同截断。
    """
    style = style or get_style()

    @tool(
        name="ask_player",
        description="向玩家提出抉择（最多 4 个选项），等待玩家选择。",
        input_schema=SCHEMA,
    )
    async def ask_player(args: dict) -> dict:
        question = args["question"]
        options = args["options"]
        if story is not None:
            story.begin_round()  # Phase 3.2：轮号占号（降级轮也算一轮，保对齐）
        try:
            # 玩家侧：按文风改写（解释器失败时 novelize 内部降级为原文）
            # Phase 3.2：story 注入前情/上一幕（novelize 内部记账 summary）
            novel = novelize_payload(
                {"question": question, "options": options},
                style=style,
                cast=cast,
                story=story,
            )
            if cast is not None and cast.scene_names:
                print(f"🎭 本场登场：{'、'.join(cast.scene_names)}", flush=True)
            pick = frontend.ask(novel["question"], novel["options"], history)
        except PlayerQuit:
            quit_signal()
            return {
                "content": [
                    {"type": "text", "text": "玩家已退出会话，请立即收尾停止工作。"}
                ]
            }
        except RollbackRequest as rr:
            # 回档：截断历史（第 n..end 作废）+ 剧情记忆同截断（按轮号
            # 过滤 + 恢复分支点上一幕）+ 置信号；不跑编剧
            if history is not None:
                history.truncate(rr.round - 1)
            if story is not None:
                story.truncate(rr.round - 1)  # Phase 3.2 回档联动
            if rollback_signal is not None:
                rollback_signal(rr.round)
            else:
                quit_signal()  # 无回档通道时退化为退出
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"玩家回档到第 {rr.round} 轮，会话即将结束，请立即收尾停止工作。",
                    }
                ]
            }

        # 记录本轮抉择（双存：原文=agent 侧、改写=玩家侧，回档菜单用改写版）
        if history is not None:
            history.record(question, novel["question"], options, novel["options"], pick)
        # Phase 3.2：提交剧情记忆的"上一幕"（含玩家所选，下一幕接续锚点）。
        # 素材由 novelize 在回填前 prepare_scene 备好（符文形态），此处
        # 补上玩家选择后提交——改写时解释器看不见玩家选择
        if story is not None:
            story.record_scene(pick)

        # 编剧：best-effort 更新角色档案（玩家阅读延迟已过去；失败沿用旧档）
        if cast is not None and not read_only and cast.scene_raw_text:
            try:
                records = call_editor(
                    style, cast.roster_text(), cast.scene_raw_text,
                    cast.scene_rune_to_term,
                )
                if records is None:
                    print("🎬 编剧不在状态（档案更新失败），旧档案照用。", flush=True)
                else:
                    new_ids = cast.update_from_editor(records, cast.scene_rune_to_term)
                    cast.save()
                    if new_ids:
                        print(f"🎬 新角色立档：{'、'.join(new_ids)}", flush=True)
            except Exception as exc:  # 编剧失败绝不能让工具调用炸掉
                print(f"🎬 编剧出错（{type(exc).__name__}），旧档案照用。", flush=True)

        label = options[pick].get("label", options[pick].get("detail", "?"))
        return {
            "content": [
                {"type": "text", "text": f"玩家选择了 [{pick + 1}] {label}"}
            ]
        }

    return ask_player
