"""Phase 2 验收：nonce 占位符方案（轻小说化）。

验收标准（项目记忆定稿）：10 条真实问题翻译后回填，技术名词零篡改。

- 默认只跑 round-trip（mask → unmask 严格相等，零网络零费用）
- --live 加跑真实链路：调 DeepSeek 网页版解释器改写 → 回填 →
  断言无残留占位符 + 技术名词零篡改（缺失/新增供人工核对）

用法：
    python phase2_accept_novel.py          # round-trip
    python phase2_accept_novel.py --live   # 全量（会真实调解释器，慢）
"""

import argparse
import json
import re
import sys
import time


def _setup_console() -> None:
    """Windows 中文控制台预防乱码（与 cli.py 同款）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


from galgame_coding.novel import (
    extract_key_terms,
    mask,
    novelize_payload,
    unmask,
)

# 10 条模拟载荷：风格贴近 tasks.py 与 Phase 1 实录，
# 覆盖技术名词/文件路径/命令/版本号等关键名词。
CASES = [
    {
        "question": "待办清单 CLI 的存储方案，你想走哪条路？",
        "options": [
            {"label": "方案A：纯标准库JSON",
             "detail": "【做法】用 json 模块读写 data.json 文件；【代价】无依赖但数据量大了要读写整个文件；【回滚】删除 data.json 即回退"},
            {"label": "方案B：sqlite3存储",
             "detail": "【做法】用 Python 内置 sqlite3 建 todo.db；【代价】多一个 .db 文件，查询要写 SQL；【回滚】删除 todo.db 即可"},
            {"label": "方案C：带截止日期版",
             "detail": "【做法】在方案B基础上加 due_date 字段，支持 due:2026-08-15 参数；【代价】CLI 解析更复杂；【回滚】去掉字段即可"},
        ],
    },
    {
        "question": "批量重命名照片，命名规则怎么定？",
        "options": [
            {"label": "规则A：拍摄日期前缀",
             "detail": "【做法】用 exif 读拍摄时间，格式化为 IMG_YYYYMMDD_HHMMSS.jpg；【代价】无 exif 的照片要回退原文件名；【回滚】保留原名映射表"},
            {"label": "规则B：递增序号",
             "detail": "【做法】按目录扫描顺序编号 001.jpg、002.jpg；【代价】顺序依赖文件系统返回；【回滚】用映射表恢复"},
        ],
    },
    {
        "question": "Markdown 表格转 CSV，输出策略选哪种？",
        "options": [
            {"label": "策略A：严格RFC4180",
             "detail": "【做法】字段一律双引号包裹，内部逗号转义；【代价】Excel 打开不友好；【回滚】换策略重跑"},
            {"label": "策略B：宽松兼容Excel",
             "detail": "【做法】非必要不加引号，用 utf-8-sig 编码输出；【代价】字段含逗号时仍需转义；【回滚】重新转换"},
        ],
    },
    {
        "question": "CLI 入口的参数解析方式选哪种？",
        "options": [
            {"label": "argparse",
             "detail": "【做法】用 argparse 定义 add/done/list 子命令；【代价】代码量稍多；【回滚】换入口重写"},
            {"label": "sys.argv 手写",
             "detail": "【做法】直接解析 sys.argv[1:]；【代价】没有帮助信息；【回滚】随手可改"},
        ],
    },
    {
        "question": "这批数据的清洗策略？",
        "options": [
            {"label": "pandas 方案",
             "detail": "【做法】read_csv 读入后按列过滤空值 dropna；【代价】引入 pandas 依赖；【回滚】保留原始 CSV"},
            {"label": "纯 Python",
             "detail": "【做法】csv 模块逐行处理，跳过空行；【代价】代码啰嗦；【回滚】原始文件不动"},
        ],
    },
    {
        "question": "网页数据怎么拿？",
        "options": [
            {"label": "requests + BeautifulSoup",
             "detail": "【做法】requests 拉 HTML，BeautifulSoup 解析表格；【代价】被反爬时要加 headers 和 UA；【回滚】本地缓存 HTML"},
            {"label": "Playwright 渲染",
             "detail": "【做法】用 Edge 通道无头渲染 JS 页面再抓；【代价】慢且依赖浏览器；【回滚】退回 requests"},
        ],
    },
    {
        "question": "Python 版本要求定到多少？",
        "options": [
            {"label": "3.10+ 新语法",
             "detail": "【做法】用 match/case 和 | 类型合并；【代价】老环境装不上；【回滚】改写为旧语法"},
            {"label": "3.8 兼容",
             "detail": "【做法】只用 typing 旧写法；【代价】代码丑一点；【回滚】无"},
        ],
    },
    {
        "question": "数据存哪里？",
        "options": [
            {"label": "SQLite 文件",
             "detail": "【做法】sqlite3 建表，常用查询建索引 idx_user；【代价】并发写有锁；【回滚】删 .db 文件"},
            {"label": "内存 dict",
             "detail": "【做法】运行时 dict 存放，结束前 dump 成 JSON；【代价】重启丢数据；【回滚】dump 前不删"},
        ],
    },
    {
        "question": "图片缩放用什么库？",
        "options": [
            {"label": "Pillow",
             "detail": "【做法】Image.open 后 resize(1280, 720)；【代价】需 pip install Pillow；【回滚】不动原图"},
            {"label": "OpenCV",
             "detail": "【做法】cv2.resize 加 INTER_AREA 插值；【代价】opencv-python 体积大；【回滚】原图先备份"},
        ],
    },
    {
        "question": "依赖装到哪里？",
        "options": [
            {"label": "venv 虚拟环境",
             "detail": "【做法】python -m venv .venv 后 pip install -r requirements.txt；【代价】每次要激活环境；【回滚】删 .venv"},
            {"label": "全局安装",
             "detail": "【做法】直接 pip install -r requirements.txt；【代价】污染全局 site-packages；【回滚】pip uninstall"},
        ],
    },
]


def _similars(a: str, terms: set[str]) -> list[str]:
    """与 a 共享 ≥3 字符前缀但又不相同的串（疑似被篡改的痕迹）。

    子串包含（"JSON" 在 "data.json" 里）是正常回填结果，不算相似。
    """
    out = []
    for b in terms:
        if b == a or a in b or b in a:
            continue
        n = 0
        for x, y in zip(a, b):
            if x != y:
                break
            n += 1
        if n >= 3 and len(b) >= 3:
            out.append(b)
    return out


def check_roundtrip(case: dict) -> tuple[bool, str]:
    """mask → unmask 严格相等（纯函数，零网络）。"""
    texts = [case["question"]] + [o["label"] + " " + o["detail"] for o in case["options"]]
    mapping: dict[str, str] = {}  # 多文本域共享编号空间（与 novelize_payload 一致）
    masked_all = []
    for t in texts:
        m, _ = mask(t, mapping)
        masked_all.append(m)
    if not mapping:
        return False, "未提取到任何关键名词（用例构造问题）"
    restored = [unmask(m, mapping) for m in masked_all]
    if restored != texts:
        return False, "round-trip 后文本不一致"
    return True, f"提取 {len(mapping)} 个关键名词"


def check_live(case: dict, idx: int) -> tuple[bool, str]:
    """真实链路：novelize → 无残留占位符 + 技术名词零篡改。"""
    original = {
        "question": case["question"],
        "options": case["options"],
    }
    t0 = time.time()
    novel = novelize_payload(original)
    dt = time.time() - t0

    if novel is original:
        return False, f"解释器调用失败（降级为原文），耗时 {dt:.0f}s"

    text_novel = json.dumps(novel, ensure_ascii=False)
    leftovers = re.findall(r"\{\{\d+\}\}", text_novel)
    if leftovers:
        return False, f"残留占位符 {leftovers}"

    # 原文关键名词 vs 回填文本
    terms_a = set()
    for t in [original["question"]] + [o["label"] + " " + o["detail"] for o in original["options"]]:
        terms_a |= extract_key_terms(t)
    terms_b = set()
    for t in [novel["question"]] + [o["label"] + " " + o["detail"] for o in novel["options"]]:
        terms_b |= extract_key_terms(t)

    missing = sorted(t for t in terms_a if t not in text_novel)
    added = sorted(terms_b - terms_a)
    # 篡改检查：只查"回填后新出现的词"与原词相似的情况；
    # 双方都是原文词（如 due_date 与 due:2026-08-15）是巧合，不算篡改
    frauds = [(t, _similars(t, terms_b - terms_a)) for t in sorted(terms_a)]
    frauds = [(t, s) for t, s in frauds if s]
    if frauds:
        return False, f"疑似篡改 {frauds}"

    if missing:
        # 缺失 = 解释器省略了某个符文所在从句。nonce 机制防篡改不防省略，
        # 报告供人工核对（提示词已要求每个符文至少出现一次）
        return False, (
            f"名词 {len(terms_a)} 个，缺失 {len(missing)}：{missing}"
            f" | 人格化新增 {len(added)} 个 | 耗时 {dt:.0f}s"
        )
    return True, (
        f"名词 {len(terms_a)} 个，缺失 0，人格化新增 {len(added)} 个"
        f" | 耗时 {dt:.0f}s"
    )


def main() -> None:
    _setup_console()
    parser = argparse.ArgumentParser(description="Phase 2 nonce 方案验收")
    parser.add_argument("--live", action="store_true", help="真实调解释器（慢）")
    args = parser.parse_args()

    print(f"== Phase 2 验收：{len(CASES)} 条载荷 ==")
    pass_cnt = 0
    for i, case in enumerate(CASES, 1):
        ok, msg = check_roundtrip(case)
        print(f"case {i:02d} round-trip: {'PASS' if ok else 'FAIL'} — {msg}")
        pass_cnt += ok

    if args.live:
        print("\n== live（真实调 DeepSeek 解释器）==")
        for i, case in enumerate(CASES, 1):
            ok, msg = check_live(case, i)
            print(f"case {i:02d} live: {'PASS' if ok else 'FAIL'} — {msg}")
            pass_cnt += ok

    print(f"\n== 汇总：{pass_cnt}/{len(CASES) * (2 if args.live else 1)} PASS ==")
    sys.exit(0 if pass_cnt == len(CASES) * (2 if args.live else 1) else 1)


if __name__ == "__main__":
    main()
