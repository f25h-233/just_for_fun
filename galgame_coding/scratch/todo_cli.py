"""待办清单 CLI —— 方案A：纯标准库 JSON 存储

用法：
    python todo_cli.py add "写周报"
    python todo_cli.py done 1
    python todo_cli.py list

数据存于 todo_data.json（与脚本同目录），结构为 list[dict]:
    [{"id": 1, "title": "写周报", "done": false}, ...]

零第三方依赖，仅用标准库 json。回滚 = 删掉 todo_data.json。
"""

import argparse
import json
import os
import sys

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "todo_data.json")


def load_tasks():
    """读取待办表；文件不存在时返回空表。"""
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tasks(tasks):
    """原子写入待办表：先写临时文件再替换，避免进程中断留下半个文件。"""
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def next_id(tasks):
    """自增 id：取当前最大 id + 1（空表从 1 开始）。"""
    return max((t["id"] for t in tasks), default=0) + 1


def cmd_add(args):
    tasks = load_tasks()
    tid = next_id(tasks)
    tasks.append({"id": tid, "title": args.title, "done": False})
    save_tasks(tasks)
    print(f"已添加 #{tid}: {args.title}")


def cmd_done(args):
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == args.id:
            t["done"] = True
            save_tasks(tasks)
            print(f"已完成 #{t['id']}: {t['title']}")
            return
    print(f"错误: 找不到 id={args.id} 的待办", file=sys.stderr)
    sys.exit(1)


def cmd_list(args):
    tasks = load_tasks()
    if not tasks:
        print("（空）还没有待办，用 add 添加。")
        return
    for t in tasks:
        mark = "[x]" if t["done"] else "[ ]"
        print(f"{mark} #{t['id']} {t['title']}")


def main():
    parser = argparse.ArgumentParser(prog="todo_cli", description="待办清单 CLI（纯标准库 JSON 存储）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="添加待办")
    p_add.add_argument("title", help="待办内容")
    p_add.set_defaults(func=cmd_add)

    p_done = sub.add_parser("done", help="标记完成")
    p_done.add_argument("id", type=int, help="待办 id（list 查看）")
    p_done.set_defaults(func=cmd_done)

    p_list = sub.add_parser("list", help="列出全部待办")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
