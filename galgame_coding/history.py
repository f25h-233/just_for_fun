"""抉择历史（Phase 3 回档）：玩家已完成抉择的记录与"已确定剧情"生成。

回档语义：玩家回到第 N 个抉择点重新选择，第 N..end 轮的记录全部作废
（truncate 截断而非"保留+过滤"——索引不重复、describe 无需参数、
语义自洽）。新会话（回档重启）继续在同一 History 上 append。

每条记录双存：原文（agent 侧看到的，prompt 重建用）+ 改写版（玩家侧
看到的，回档菜单展示用——玩家刚读过的就是改写版，展示改写版体验一致；
novelize 降级时两者相同）。

History 是单次运行内的会话状态，不持久化（Ctrl+C 打断即丢失；
cast.json 是周目级资产才有 finally 兜底）。已知边界，见 CLAUDE.md。
"""

from dataclasses import dataclass


@dataclass
class ChoiceRecord:
    """一轮已完成的抉择。

    index 是轮号（1-based）；question/picked_label 是原文（agent 侧），
    question_novel/picked_label_novel 是改写版（玩家侧）。
    """

    index: int
    question: str
    question_novel: str
    picked_label: str
    picked_label_novel: str
    picked_index: int


class History:
    """已完成抉择的时序记录，供回档菜单展示与 prompt 重建。"""

    def __init__(self) -> None:
        self.records: list[ChoiceRecord] = []

    def record(
        self,
        question: str,
        question_novel: str,
        options: list[dict],
        options_novel: list[dict],
        picked_index: int,
    ) -> ChoiceRecord:
        """记录一轮抉择（双存原文 + 改写版），轮号自动 = len+1。"""
        rec = ChoiceRecord(
            index=len(self.records) + 1,
            question=question,
            question_novel=question_novel,
            picked_label=options[picked_index].get("label", "?"),
            picked_label_novel=options_novel[picked_index].get("label", "?"),
            picked_index=picked_index,
        )
        self.records.append(rec)
        return rec

    def truncate(self, keep: int) -> None:
        """回档：只保留前 keep 轮（第 keep+1..end 作废）。keep ≥ 0。"""
        if keep < len(self.records):
            del self.records[keep:]

    def describe(self) -> str:
        """生成"已确定剧情"文本（prompt 重建注入用，取原文）。

        空历史返回空串。每轮一行：轮号 + 原文 question + 所选原文 label。
        """
        if not self.records:
            return ""
        lines = []
        for rec in self.records:
            lines.append(f"{rec.index}. 问：{rec.question} → 选：{rec.picked_label}")
        return "\n".join(lines)
