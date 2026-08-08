"""前端抽象：ask_player 的渲染与输入界面。

Phase 1 只有终端实现（frontends/terminal.py）；Phase 4 换 pygame 时
新增 frontends/pygame.py，宿主核心与工具定义完全不用动。
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .history import History


class PlayerQuit(Exception):
    """玩家选择退出（输入 q 或 Ctrl+C）。

    前端内部捕获后抛出，由工具层转成退出信号，宿主收到后切断会话。
    """


class RollbackRequest(Exception):
    """玩家要求回档到第 round 个抉择点（1-based）。

    前端（回档子菜单）捕获输入后抛出；工具层捕获后截断历史、置回档
    信号并让 agent 收尾——宿主收到信号后切断会话、重建 prompt 重启
    （SDK 会话内无法回退，回档 = 新会话）。
    """

    def __init__(self, round: int) -> None:
        super().__init__(round)
        self.round = round


class Frontend(Protocol):
    def ask(
        self, question: str, options: list[dict], history: "History | None" = None
    ) -> int:
        """渲染抉择并等待玩家输入，返回被选选项的下标（0-based）。

        history: 已完成抉择的记录（Phase 3 回档菜单用，可空）。
        玩家选择回档时抛 RollbackRequest，退出时抛 PlayerQuit。
        """
        ...
