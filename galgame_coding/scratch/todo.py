"""todo.py —— 待办清单 CLI（方案C：JSON + 截止日期版）。

三个命令：
    python todo.py add  <内容> [--due YYYY-MM-DD]   添加待办（可带截止日期）
    python todo.py done <id>                         标记完成
    python todo.py list [--due YYYY-MM-DD]           列出（可过滤某截止日期）

存储：标准库 json，数据在单个 todo.json 文件里，无第三方依赖。
文件默认与脚本同目录（todo.json），可用 --file 指定其他路径。

方案C相对方案A的增量：
- 每条任务带可选 due（截止日期，YYYY-MM-DD），add 时用 --due 传入；
- list 对未完成任务标注「已逾期 / 临期（3 天内）/ 正常」状态；
- list --due <日期> 只显示截止日期为指定日期的任务。
去掉 due 相关逻辑即退回方案A，JSON 数据结构向后兼容（due 可为 null）。
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

DEFAULT_FILE = Path(__file__).parent / "todo.json"
DUE_SOON_DAYS = 3  # 距截止不足等于此天数视为临期


def parse_date(text: str) -> date:
    """argparse type：解析 YYYY-MM-DD，非法格式报错退出。"""
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"日期格式应为 YYYY-MM-DD，收到: {text!r}"
        )


def load_data(path: Path) -> dict:
    """读取 todo.json；文件不存在返回空数据，损坏时报错退出。"""
    if not path.exists():
        return {"tasks": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"错误: 无法读取 {path}（{e}）", file=sys.stderr)
        print("提示: 文件损坏可手动修复或删除后重建", file=sys.stderr)
        raise SystemExit(1)
    data.setdefault("tasks", [])
    return data


def save_data(path: Path, data: dict) -> None:
    """原子写 todo.json：先写临时文件再替换，避免写一半崩溃损坏数据。"""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        os.unlink(tmp)
        print(f"错误: 无法写入 {path}（{e}）", file=sys.stderr)
        raise SystemExit(1)


def next_id(tasks: list[dict]) -> int:
    """新任务 id：现有最大 id + 1（手动编辑删行也不会复用 id）。"""
    return max((t["id"] for t in tasks), default=0) + 1


def cmd_add(args: argparse.Namespace) -> int:
    """添加一条待办（due 可选），返回新任务的 id。"""
    path = Path(args.file)
    data = load_data(path)
    tasks = data["tasks"]
    task = {
        "id": next_id(tasks),
        "content": args.content,
        "done": False,
        "due": args.due.isoformat() if args.due else None,
    }
    tasks.append(task)
    save_data(path, data)
    suffix = f"，截止 {task['due']}" if task["due"] else ""
    print(f"已添加 #{task['id']}: {task['content']}{suffix}")
    return 0


def cmd_done(args: argparse.Namespace) -> int:
    """把指定 id 的任务标记为完成；id 不存在则报错。"""
    path = Path(args.file)
    data = load_data(path)
    for task in data["tasks"]:
        if task["id"] == args.id:
            task["done"] = True
            save_data(path, data)
            print(f"已完成 #{args.id}")
            return 0
    print(f"错误: 找不到 id={args.id} 的任务", file=sys.stderr)
    return 1


def due_status(task: dict, today: date) -> str:
    """任务截止状态文字；已完成或无截止日期返回 None。"""
    if task["done"] or not task["due"]:
        return None
    delta = (date.fromisoformat(task["due"]) - today).days
    if delta < 0:
        return f"已逾期 {-delta} 天"
    if delta <= DUE_SOON_DAYS:
        return f"剩 {delta} 天到期"
    return f"截止 {task['due']}"


def cmd_list(args: argparse.Namespace) -> int:
    """列出任务：未完成在前按 id 升序，--due 时只显示指定截止日期的任务。"""
    data = load_data(Path(args.file))
    tasks = data["tasks"]
    if args.due:
        target = args.due.isoformat()
        tasks = [t for t in tasks if t.get("due") == target]
    if not tasks:
        print("（暂无待办，用 add 添加）")
        return 0
    tasks.sort(key=lambda t: (t["done"], t["id"]))
    today = date.today()
    for task in tasks:
        mark = "[x]" if task["done"] else "[ ]"
        line = f"{mark} #{task['id']} {task['content']}"
        if task["done"]:
            line += "（已完成）"
        else:
            status = due_status(task, today)
            if status:
                line += f"（{status}）"
        print(line)
    pending = sum(1 for t in tasks if not t["done"])
    print(f"\n共 {len(tasks)} 条，未完成 {pending} 条")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="todo", description="待办清单 CLI（JSON + 截止日期版）"
    )
    parser.add_argument("--file", default=str(DEFAULT_FILE),
                        help="数据文件路径（默认: todo.json）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="添加待办")
    p_add.add_argument("content", help="待办内容")
    p_add.add_argument("--due", type=parse_date, metavar="YYYY-MM-DD",
                       help="截止日期（可选）")
    p_add.set_defaults(func=cmd_add)

    p_done = sub.add_parser("done", help="标记完成")
    p_done.add_argument("id", type=int, help="任务 id（list 查看）")
    p_done.set_defaults(func=cmd_done)

    p_list = sub.add_parser("list", help="列出任务")
    p_list.add_argument("--due", type=parse_date, metavar="YYYY-MM-DD",
                        help="只显示截止日期为此日的任务")
    p_list.set_defaults(func=cmd_list)

    return parser


def main() -> int:
    # Windows 下重定向 stdout 时 Python 默认用 locale 编码（GBK），
    # 强制 UTF-8 保证中文在任意终端可读。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
