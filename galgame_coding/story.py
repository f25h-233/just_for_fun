"""剧情记忆（Phase 3.2）：跨轮剧情连续性（主线贯穿）的宿主侧数据层。

解释器副 agent 是无状态调用（每轮一次，无 API 费用），剧情记忆必须
由宿主侧维护、调用时注入。设计定稿（四路调研综合，见 CLAUDE.md）：

- 双层记忆（RecurrentGPT 实证，与"无状态调用+宿主注入"同构）：
  短时 = 上一幕改写全文（prev_scene，直接接续，注入在最接近载荷处）；
  长时 = 每幕 1-3 句摘要（summaries，滚动窗口：首条全局锚点 + 最近 6 条，
  防记忆膨胀——只增不删会让注入段噪声越来越大）。
- 写回契约：解释器同一次调用顺带输出 summary_delta（1-3 句摘要）+
  importance（0-3 分），宿主记账（fail-soft：缺失/坏格式静默沿用旧梗概，
  绝不进渲染路径——与 cast.json 同模式，零新增调用）。
- 生命周期：会话级，与 History 同级（回档即 truncate、Ctrl+C 即丢失；
  cast.json 是周目级资产才有 finally 兜底）。
- 注入顺序固定（实测"最后注入优先级最高"）：
  文风模板 → roster → 剧本纪律 → 梗概 → 上一幕结尾 → 载荷 → 输出要求。
- 回档对齐（轮号机制，2026-08-09 定稿）：tools 每轮（**含降级轮**）
  begin_round 占号；条目携带轮号，truncate 按**轮号过滤**而非计数——
  降级轮无条目，计数截断会错位（作废分支的摘要残留进新会话）。
  上一幕按轮存档（_scenes），truncate 恢复分支点的接续锚点。
"""

from dataclasses import dataclass, field

SUMMARY_KEEP_HEAD = 1   # 保留的全局锚点条目数（首条，主线之根）
SUMMARY_KEEP_TAIL = 6   # 保留的最近条目数
SUMMARY_MAX_LEN = 120   # 单条摘要上限（字）
PREV_SCENE_MAX = 600    # 上一幕注入字数上限（防注入段膨胀）


def _clamp_importance(v) -> int:
    """importance 钳制 0-3；非整数/缺失 → 0。"""
    if isinstance(v, int) and not isinstance(v, bool):
        return max(0, min(3, v))
    return 0


@dataclass
class SummaryEntry:
    text: str          # 本幕 1-3 句摘要
    importance: int    # 0-3，解释器给分、宿主钳制
    round: int         # 所属轮次（与 History 轮号对齐；降级轮无条目但占号）


@dataclass
class _Scene:
    """一幕的完整改写文本（符文形态），按轮存档供回档恢复上一幕。"""

    round: int
    text: str


@dataclass
class StoryMemory:
    """剧情记忆：上一幕全文 + 每幕摘要（滚动窗口）。

    record_summary（写回契约记账，novelize 改写成功时调用）与
    record_scene（上一幕提交，tools.py 玩家选择后调用）。
    **nonce 隔离纪律**：prev_scene/summaries 存**符文形态**（{{N}}，
    含 {{C数字}}）——前情要注入给解释器，泄漏原词会破坏 nonce 方案
    的"解释器只见符文"核心隔离。玩家选择是宿主在 ask 后才知道的，
    用 prepare_scene/record_scene 两段式补上（改写时准备、选择后提交）。

    **轮号对齐（回档联动）**：tools 每轮调 begin_round（含降级轮——
    降级轮无条目但占号，保证条目轮号与 History 轮号一一对齐）；
    truncate(keep) 按轮号过滤（计数截断会被降级轮错位）并恢复
    分支点的上一幕（_scenes 按轮存档）。tools.py 回档路径调用。
    """

    prev_scene: str = ""
    summaries: list[SummaryEntry] = field(default_factory=list)
    _scenes: list[_Scene] = field(default_factory=list, repr=False)
    _round_no: int = 0
    _pending_round: int | None = field(default=None, repr=False)
    _pending_question: str | None = field(default=None, repr=False)
    _pending_labels: list[str] | None = field(default=None, repr=False)

    # ---------- 轮号 ----------

    def begin_round(self) -> None:
        """本轮开始（tools 每轮调用一次，含降级轮——占号保对齐）。"""
        self._round_no += 1

    # ---------- 记账 ----------

    def record_summary(self, delta: str, importance=None) -> None:
        """追加一幕摘要（写回契约）。非字符串/空白忽略；importance 钳制。"""
        if not isinstance(delta, str):
            return  # fail-soft：坏格式静默忽略（novelize 层有守卫，此处兜底）
        text = delta.strip()[:SUMMARY_MAX_LEN]
        if text:
            self.summaries.append(SummaryEntry(
                text=text, importance=_clamp_importance(importance),
                round=self._round_no,
            ))
            self._trim()

    def prepare_scene(self, question: str, options: list[dict]) -> None:
        """改写成功时准备上一幕素材（novelize 回填前调用，符文形态）。

        options 传解释器输出的改写版（其 label 是符文形态）。
        """
        self._pending_round = self._round_no
        self._pending_question = question
        self._pending_labels = [o.get("label", "") for o in options]

    def record_scene(self, picked_index: int) -> None:
        """提交上一幕（tools.py 玩家选择后调用）：含玩家所选。

        上一幕只在改写成功时更新——降级轮（解释器失败）没有可接续的
        剧情，保留旧上一幕；这样 prev_scene 永远只有符文形态。
        按轮存档（_scenes），回档 truncate 据此恢复分支点的上一幕。
        """
        if self._pending_question is None or self._pending_labels is None:
            return  # 本轮降级（无 prepare_scene），上一幕保持不变
        label = ""
        if 0 <= picked_index < len(self._pending_labels):
            label = self._pending_labels[picked_index]
        self.prev_scene = f"{self._pending_question}（这一场，我选择了：{label}）"
        self._scenes.append(_Scene(round=self._pending_round, text=self.prev_scene))
        self._pending_round = None
        self._pending_question = None
        self._pending_labels = None

    def _trim(self) -> None:
        """滚动窗口：首条（全局锚点）+ 最近 KEEP_TAIL 条。"""
        if len(self.summaries) > SUMMARY_KEEP_HEAD + SUMMARY_KEEP_TAIL:
            keep = self.summaries[:SUMMARY_KEEP_HEAD] + self.summaries[-SUMMARY_KEEP_TAIL:]
            self.summaries = keep

    def truncate(self, keep: int) -> None:
        """回档：只保留前 keep 轮（第 keep+1..end 作废），与 History 同语义。

        **按轮号过滤而非计数**——降级轮（无摘要/无场景）不破坏对齐：
        轮号 ≤ keep 的条目保留（0 号 = 未 begin_round 的直调测试条目，
        视为早于一切轮次）。keep=0 时全部作废（回档到第一幕）。
        上一幕恢复为保留轮里最后一幕的全文（分支点接续锚点）；
        保留轮全为降级轮时为空。清空未提交的 pending（其轮号必然
        > keep——回档只发生在当轮 ask 期间）；_round_no 重置为 keep，
        新会话下一轮 begin_round 后与 History 轮号重新对齐。
        """
        if keep == 0:
            self.summaries = []
            self._scenes = []
            self.prev_scene = ""
        else:
            self.summaries = [e for e in self.summaries if e.round <= keep]
            self._scenes = [s for s in self._scenes if s.round <= keep]
            self.prev_scene = self._scenes[-1].text if self._scenes else ""
        self._pending_round = None
        self._pending_question = None
        self._pending_labels = None
        self._round_no = keep

    # ---------- 注入文本 ----------

    def context_text(self) -> str:
        """【前情】注入段：梗概（首条 + 最近 6 条）。空记忆返回空串。"""
        if not self.summaries:
            return ""
        return "\n".join(f"{i + 1}. {e.text}" for i, e in enumerate(self.summaries))

    def prev_scene_text(self) -> str:
        """【上一幕结尾】注入段：最近一幕改写全文。

        截断取**尾部**不取头部——幕尾钩与选择后果在结尾，接续看的是结尾。
        """
        if not self.prev_scene:
            return ""
        text = self.prev_scene
        if len(text) > PREV_SCENE_MAX:
            text = "……" + text[-PREV_SCENE_MAX:]
        return text
