"""入口：python -m galgame_coding.cli ["任务描述"] [--menu]

- 带任务参数：直接跑该任务
- --menu：启动菜单，可选示例任务（tasks.py）或输入自定义任务（run.bat 走这里）
- 无参数：跑第一个示例任务（待办 CLI 存储方案抉择，专供验收）
"""

import argparse
import asyncio
import sys

from .galgame import run
from .style import STYLES, get_style
from .tasks import DEMO_TASKS


def _setup_console() -> None:
    """Windows 中文控制台预防乱码：stdout/stderr/stdin 统一 UTF-8。"""
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass  # 非 Windows 或无 reconfigure 的流，忽略


def _choose_task() -> str:
    """启动菜单：从示例任务里选，或输入自定义任务，返回任务文本。"""
    n = len(DEMO_TASKS)
    print("\n🎮 选择要进行的任务：", flush=True)
    for i, t in enumerate(DEMO_TASKS, 1):
        print(f"  [{i}] {t['name']} —— {t['desc']}", flush=True)
    print(f"  [{n + 1}] 输入自定义任务", flush=True)
    while True:
        try:
            raw = input("你的选择（编号 / q 退出）：").strip()
        except KeyboardInterrupt:
            raise SystemExit()
        if raw.lower() in ("q", "quit"):
            raise SystemExit()
        if raw.isdigit():
            i = int(raw)
            if 1 <= i <= n:
                return DEMO_TASKS[i - 1]["task"]
            if i == n + 1:
                custom = input("输入任务描述：").strip()
                if custom:
                    return custom
        print(f"无效输入：请输入 1-{n + 1} 之间的编号。", flush=True)


def main() -> None:
    _setup_console()
    parser = argparse.ArgumentParser(description="Galgame Coding 文本版前端")
    parser.add_argument("task", nargs="?", help="任务描述；缺省用第一个示例任务")
    parser.add_argument("--menu", action="store_true", help="启动菜单：选示例任务或自定义")
    parser.add_argument(
        "--novel-lite",
        action="store_true",
        help="轻小说化降级：不调解释器副 agent，改为提示词要求 agent 自写日轻口吻",
    )
    parser.add_argument(
        "--style",
        choices=sorted(STYLES),
        default="novel",
        help="文风（解释器改写口吻），默认 novel",
    )
    parser.add_argument(
        "--reset-cast",
        action="store_true",
        help="清空角色档案（新周目/换角色）",
    )
    args = parser.parse_args()

    if args.novel_lite and args.style != "novel":
        print(f"⚠ --novel-lite 只支持默认文风，忽略 --style {args.style}。", flush=True)
        args.style = "novel"
    task = _choose_task() if args.menu else (args.task or None)
    try:
        asyncio.run(run(
            task,
            light_novel=args.novel_lite,
            style=get_style(args.style),
            reset_cast=args.reset_cast,
        ))
    except KeyboardInterrupt:
        print("\n🚪 玩家退出。", flush=True)


if __name__ == "__main__":
    main()
