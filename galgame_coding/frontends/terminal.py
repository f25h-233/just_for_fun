"""终端前端：问题 + 编号菜单，detail 按【做法】【代价】【回滚】切分渲染。

设计决策：
- 编号从 1 开始（人类友好），返回 0-based 下标
- 三要素切分兼做"格式守门员"：缺任一要素时打 ⚠ 告警，
  一次运行就能侧面验证 prompt 约束是否真的生效
- 非法输入循环重试；q / Ctrl+C 转 PlayerQuit 优雅退出；
  r 进入回档子菜单（Phase 3）——选目标轮次后抛 RollbackRequest
- 颜色用 ANSI 转义（Windows 11 的终端/控制台均支持），不依赖第三方库
"""

from ..frontend import PlayerQuit, RollbackRequest

SEP = "─" * 56

_TAGS = ("【做法】", "【代价】", "【回滚】")
_TAG_COLORS = {
    "【做法】": "\x1b[36m",  # 青色
    "【代价】": "\x1b[33m",  # 黄色
    "【回滚】": "\x1b[32m",  # 绿色
}
_RESET = "\x1b[0m"
_WARN = "\x1b[31m"  # 红色


def _split_detail(detail: str) -> tuple[list[str], bool]:
    """按【做法】【代价】【回滚】切分 detail。

    返回 (切分后的文本段列表, 三要素是否齐全)。段文本保留原 tag，
    渲染时据此上色。tag 顺序无关，按出现位置排序。
    """
    positions = [(tag, detail.find(tag)) for tag in _TAGS]
    if any(pos == -1 for _, pos in positions):
        return [detail], False
    positions.sort(key=lambda kv: kv[1])
    segments = []
    for i, (tag, pos) in enumerate(positions):
        end = positions[i + 1][1] if i + 1 < len(positions) else len(detail)
        segments.append(detail[pos:end].strip())
    return segments, True


def _render_option(i: int, opt: dict) -> None:
    label = opt.get("label") or opt.get("detail", "?").splitlines()[0][:20]
    print(f"  [{i}] {label}", flush=True)
    segments, complete = _split_detail(opt.get("detail", ""))
    for seg in segments:
        color = next((_TAG_COLORS[t] for t in _TAGS if seg.startswith(t)), "")
        print(f"      {color}{seg}{_RESET if color else ''}", flush=True)
    if not complete:
        print(f"      {_WARN}⚠ 该选项缺【做法】【代价】【回滚】三要素{_RESET}", flush=True)


def _rollback_menu(history: "History | None") -> int:
    """回档子菜单：列出已完成抉择，玩家选目标轮次，返回轮号（1-based）。

    只列已确定轮次（1..len），当前轮不可回档（重选直接输编号）。
    子菜单内 Ctrl+C / q 与主菜单一致 → PlayerQuit（整个会话退出）。
    """
    records = list(history.records) if history is not None else []
    if not records:
        print("  ⚠ 还没有可回档的抉择点（至少完成一轮抉择后才能回档）。", flush=True)
        return 0
    print(f"\n{SEP}", flush=True)
    print("⏪ 回档：选择要回到的抉择点（回档后从此处重新分叉）：", flush=True)
    for rec in records:
        q = rec.question_novel or rec.question
        print(f"  [{rec.index}] {q[:40]}… 曾选: {rec.picked_label_novel or rec.picked_label}", flush=True)
    print(SEP, flush=True)
    while True:
        try:
            raw = input("回档到第几轮（编号 / q 返回退出）：").strip()
        except KeyboardInterrupt:
            print("\n🚪 玩家按下了 Ctrl+C。", flush=True)
            raise PlayerQuit() from None
        if raw.lower() in ("q", "quit"):
            raise PlayerQuit()
        if raw.isdigit() and 1 <= int(raw) <= len(records):
            return int(raw)
        print(f"无效输入：请输入 1-{len(records)} 之间的编号。", flush=True)


class TerminalFrontend:
    """终端前端：问题 + 编号菜单，detail 按【做法】【代价】【回滚】切分渲染。

    实现 Frontend Protocol（frontend.py）：宿主传实例，工具层调 .ask()。
    """

    def ask(
        self, question: str, options: list[dict], history: "History | None" = None
    ) -> int:
        """渲染抉择菜单，等待玩家输入，返回 0-based 选项下标。

        history 为已完成抉择的记录（Phase 3 回档）：输入 r 进入回档
        子菜单，玩家选目标轮次后抛 RollbackRequest(n)。
        """
        print(f"\n{SEP}", flush=True)
        print(f"🎮 抉择：{question}", flush=True)
        for i, opt in enumerate(options, 1):
            _render_option(i, opt)
        print(SEP, flush=True)

        while True:
            try:
                raw = input("你的选择（编号 / r 回档 / q 退出）：").strip()
            except KeyboardInterrupt:
                print("\n🚪 玩家按下了 Ctrl+C。", flush=True)
                raise PlayerQuit() from None
            if raw.lower() in ("q", "quit"):
                raise PlayerQuit()
            if raw.lower() in ("r", "rollback"):
                n = _rollback_menu(history)
                if n:
                    raise RollbackRequest(n)
                continue  # 空历史：提示后回到主菜单
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return int(raw) - 1
            print(f"无效输入：请输入 1-{len(options)} 之间的编号（r 可回档）。", flush=True)
