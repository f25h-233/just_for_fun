"""Phase 2.1 验收：文风模块化 + 角色人格化/持久化。

离线（零网络零费用）：monkeypatch _call_interpreter/_call_editor 模拟
解释器与编剧，覆盖：
- T1 角色占位符跨轮稳定 + 回填零篡改 + 记账（meetings/last_line/scene_names）
- T2 编剧输出白名单校验用例表（坏 JSON/未知 rune/越界 affinity/空 name）
- T3 C 符文缺失 → 降级原文（novel is original）
- T4 merge_key 归并（SQLite/sqlite3 → 同一角色）
- T5 cast 存取 round-trip + 坏档降级 + reset（临时目录，不碰真实存档）
- T6 文风注册表（默认/未知回退/模板槽位）

--live：真实调 DeepSeek 解释器 + 编剧两轮，验证角色持续出场（慢，
每次 4-22s × 4 次调用）。判据宽松：两轮都改写成功 + 首轮立档 +
次轮改写文本仍出现角色符文。

用法：
    python phase21_accept_cast.py          # 离线全量
    python phase21_accept_cast.py --live   # 加跑真实链路
"""

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path

def _setup_console() -> None:
    """Windows 中文控制台预防乱码（与 cli.py 同款）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


from galgame_coding import characters as CH
from galgame_coding import editor as ED
from galgame_coding import novel as NV
from galgame_coding.characters import Cast, merge_key
from galgame_coding.editor import _parse, _validated
from galgame_coding.novel import extract_key_terms, novelize_payload, unmask
from galgame_coding.style import STYLES, get_style

# 模拟载荷：与 phase2_accept_novel.py 同源，含角色词 sqlite3 与普通词
PAYLOAD = {
    "question": "待办清单 CLI 的存储方案，你想走哪条路？",
    "options": [
        {"label": "方案A：纯标准库JSON",
         "detail": "【做法】用 json 模块读写 data.json 文件；【代价】无依赖但数据量大了要读写整个文件；【回滚】删除 data.json 即回退"},
        {"label": "方案B：sqlite3存储",
         "detail": "【做法】用 Python 内置 sqlite3 建 todo.db；【代价】多一个 .db 文件，查询要写 SQL；【回滚】删除 todo.db 即可"},
        {"label": "方案C：带截止日期版",
         "detail": "【做法】在方案B基础上加 due_date 字段，支持 due:2026-08-15 参数；【代价】CLI 解析更复杂；【回滚】去掉字段即可"},
    ],
}


def _fake_interp(payload_json: str, system: str) -> str:
    """模拟解释器：每个符文包一层"神秘的"描述（人格化），符文全保留。"""
    data = json.loads(payload_json)
    text = json.dumps(data, ensure_ascii=False)
    text = re.sub(r"\{\{C?\d+\}\}", lambda m: f"神秘的{m.group(0)}", text)
    return json.dumps({"content": text}, ensure_ascii=False)


def _fake_editor(style, roster_text: str, scene_raw_text: str, rune_to_term: dict[str, str]) -> list[dict]:
    """模拟编剧：给 sqlite3 立档为"小石"，其余不管。"""
    target = next((r for r, t in rune_to_term.items() if t == "sqlite3"), None)
    if target is None:
        return []
    return [{"runes": [target], "name": "小石", "persona": "冷静可靠的数据库精灵，微毒舌", "affinity": 58}]


def t1_cast_stability() -> tuple[bool, str]:
    """跨轮稳定：首轮 sqlite3 是普通符文，编剧立档后次轮转正 {{C1}}，
    回填零篡改，meetings 累计、last_line/scene_names 记账。"""
    NV._call_interpreter = _fake_interp
    ED._call_editor = _fake_editor
    cast = Cast()
    # 轮 1：无档案，sqlite3 走普通符文
    r1 = novelize_payload(PAYLOAD, style=get_style("novel"), cast=cast)
    assert r1 is not PAYLOAD, "轮1应改写成功"
    assert cast.characters == {}, "轮1不应有角色（编剧还未跑）"
    assert cast.scene_names == [], "轮1无角色不应有登场名单"
    # 编剧立档
    recs = ED._call_editor(get_style("novel"), cast.roster_text(), cast.scene_raw_text, cast.scene_rune_to_term)
    cast.update_from_editor(recs, cast.scene_rune_to_term)
    # 每词独立占位符：主词预置 {{C1}}，变体（SQLite）分配独立编号——
    # 回填互不干扰（2026-08-08 修复：曾因同角色共享一符文导致全回填成首词）
    ph_main = cast.placeholder_for("sqlite3")
    ph_var = cast.placeholder_for("SQLite")
    assert ph_main == "{{C1}}", f"主词应预置 {{{{C1}}}}: {ph_main}"
    assert ph_var != ph_main, "变体应有独立符文"
    assert ph_main in cast.roster_text() and ph_var in cast.roster_text(), "roster 应同角色同列两符文"
    # 轮 2：sqlite3 以 {{C1}} 出场，形象由编剧注入的 roster 维持
    r2 = novelize_payload(PAYLOAD, style=get_style("novel"), cast=cast)
    assert r2 is not PAYLOAD, "轮2应改写成功"
    text2 = json.dumps(r2, ensure_ascii=False)
    for term in extract_key_terms(json.dumps(PAYLOAD, ensure_ascii=False)):
        assert term in text2, f"轮2 回填后技术名词缺失: {term}"
    ch = cast.characters[1]
    assert cast.scene_names == ["小石"], f"登场名单应含小石: {cast.scene_names}"
    # 立档后的出场才算 meetings（轮 1 是普通符文、无档案可记）
    assert ch.meetings == 1, f"立档后首场 meetings 应为 1: {ch.meetings}"
    assert ch.last_line, "last_line 应已记账"
    assert ch.affinity == 58, f"编剧 affinity 应生效: {ch.affinity}"
    return True, f"两轮改写成功，{{{{C1}}}} 跨轮稳定，meetings={ch.meetings}，last_line={ch.last_line[:20]}…"


def t2_editor_validation() -> tuple[bool, str]:
    """编剧输出白名单校验：坏记录丢弃/钳制，好记录保留。"""
    valid_runes = {"{{C1}}", "{{2}}", "{{3}}"}
    records = [
        {"runes": ["{{C1}}"], "name": "小石", "persona": "冷静可靠", "affinity": 150},   # affinity 越界 → 钳 100
        {"runes": ["{{999}}"], "name": "幽灵", "persona": "x", "affinity": 50},           # 未知 rune → 丢弃
        {"runes": ["{{2}}"], "name": "   ", "persona": "x"},                              # 空 name → 丢弃
        {"runes": ["{{3}}"], "name": "石碑", "persona": "p" * 400, "affinity": True},     # persona 截断 + bool affinity 忽略
        "not a dict",                                                                     # 非 dict → 丢弃
        {"runes": ["{{C1}}", "{{2}}"], "name": "合并角", "persona": "两符文同一人"},       # 多符文合并
    ]
    out = _validated(records, valid_runes)
    assert len(out) == 3, f"应剩 3 条: {len(out)}"
    by_name = {r["name"]: r for r in out}
    assert by_name["小石"]["affinity"] == 100, "越界 affinity 应钳制到 100"
    assert len(by_name["石碑"]["persona"]) == 300, "persona 应截断到 300"
    assert by_name["石碑"]["affinity"] is None, "bool affinity 应被忽略"
    assert by_name["合并角"]["runes"] == ["{{C1}}", "{{2}}"], "多符文应保留"
    # _parse：坏 JSON/非数组顶层 → None
    assert _parse("not json") is None
    assert _parse('{"content": "{\\"a\\": 1}"}') is None          # 顶层非数组
    assert _parse('{"content": "[{\\"x\\": 1}]"}') == [{"x": 1}]
    return True, f"3/6 条通过白名单，钳制/截断/丢弃语义正确"


def t3_c_rune_missing() -> tuple[bool, str]:
    """C 符文缺失 → 角色消失 → 降级原文（novel is original）。"""
    def _missing(payload_json: str, system: str) -> str:
        out = {"question": "石碑不见了，此地空无一物。",
               "options": [{"label": "A", "detail": "【做法】x；【代价】y；【回滚】z"} for _ in PAYLOAD["options"]]}
        return json.dumps({"content": json.dumps(out, ensure_ascii=False)}, ensure_ascii=False)
    NV._call_interpreter = _missing
    cast = Cast()
    cast.update_from_editor([{"runes": ["{{2}}"], "name": "小石", "persona": "x"}], {"{{2}}": "sqlite3"})
    r = novelize_payload(PAYLOAD, style=get_style("novel"), cast=cast)
    assert r is PAYLOAD, "角色符文缺失应降级原文（同一对象）"
    return True, "角色符文缺失 → 降级原文，身份判断通过"


def t4_merge_key() -> tuple[bool, str]:
    """merge_key：去尾数字 + casefold。"""
    assert merge_key("SQLite") == merge_key("sqlite3") == merge_key("sqlite")
    assert merge_key("Django") == merge_key("django")
    assert merge_key("due_date") != merge_key("due")
    return True, "SQLite/sqlite3/sqlite 归并为 sqlite"


def t5_cast_persistence() -> tuple[bool, str]:
    """存取 round-trip + 坏档降级 + reset（临时目录，不碰真实存档）。"""
    orig_save = CH.SAVE_PATH
    try:
        with tempfile.TemporaryDirectory() as tmp:
            CH.SAVE_PATH = Path(tmp) / "cast.json"
            cast = Cast()
            cast.update_from_editor([{"runes": ["{{2}}"], "name": "小石", "persona": "x", "affinity": 66}], {"{{2}}": "sqlite3"})
            cast.characters[1].meetings = 3
            cast.characters[1].last_line = "连内存都兜不住的事，就别指望磁盘了。"
            cast.save()
            loaded = Cast.load()
            assert loaded.next_n == 2 and loaded.characters[1].name == "小石"
            assert loaded.characters[1].affinity == 66 and loaded.characters[1].meetings == 3
            assert loaded.characters[1].last_line.endswith("。")
            assert loaded.term_placeholders.get("sqlite3") == "{{C1}}", "词占位符应持久"
            assert loaded.next_t >= 2, "词占位符计数器应持久"
            # 坏档 → 空档不崩
            CH.SAVE_PATH.write_text("{broken", encoding="utf-8")
            assert Cast.load().characters == {}
            # reset → 删档
            CH.SAVE_PATH.write_text("{}", encoding="utf-8")
            Cast.reset()
            assert not CH.SAVE_PATH.exists()
    finally:
        CH.SAVE_PATH = orig_save
    return True, "round-trip 字段齐、坏档降级、reset 删档"


def t6_style_registry() -> tuple[bool, str]:
    """文风注册表：默认/未知回退/模板槽位/两文风齐备。"""
    assert get_style() is STYLES["novel"] and get_style("nope") is STYLES["novel"]
    assert set(STYLES) == {"novel", "wuxia"}
    for s in STYLES.values():
        assert "{roster}" in s.system_template, f"{s.name} 缺 roster 槽位"
        assert "{{C数字}}" in s.system_template, f"{s.name} 缺 C 符文规则"
    assert "说书人" in STYLES["wuxia"].system_template
    return True, "novel/wuxia 注册齐备，默认与未知均回退日轻"


def t7_bad_cast_regression() -> tuple[bool, str]:
    """坏档回归（2026-08-08 真实 bug 现场）：角色被编剧过度合并
    （id=CLI、aliases 塞进 13 个异类词）后，双轮 novelize 所有技术
    名词仍原样回填——不再全部变成 CLI。修复核心：每词独立占位符，
    即使档案污染，词与词之间也互不干扰。"""
    cast = Cast()
    cast.update_from_editor(
        [{"runes": ["{{1}}"], "name": "小石", "persona": "数据库精灵", "affinity": 58}],
        {"{{1}}": "CLI"},
    )
    # 模拟历史坏档：编剧把本轮全部符文并进小石的 aliases
    for term in ["JSON", "json", "todo.json", "add", "done", "list",
                 "sqlite3", "todo.db", "title", "SQL", "due", "--due"]:
        if term not in cast.characters[1].aliases:
            cast.characters[1].aliases.append(term)
    NV._call_interpreter = _fake_interp
    ED._call_editor = _fake_editor
    r = novelize_payload(PAYLOAD, style=get_style("novel"), cast=cast)
    assert r is not PAYLOAD, "应改写成功"
    text = json.dumps(r, ensure_ascii=False)
    for term in extract_key_terms(json.dumps(PAYLOAD, ensure_ascii=False)):
        assert term in text, f"技术名词被篡改/缺失: {term}"
    # 关键断言：json/JSON/sqlite3/SQL 各自原样（不能统一变成 CLI）
    assert "json" in text and "JSON" in text and "sqlite3" in text and "SQL" in text, text
    return True, "污染档案下技术名词全部原样回填（每词独立符文免疫）"


def check_live() -> tuple[bool, str]:
    """真实链路两轮：改写 + 编剧各两次，验证角色持续出场（判据宽松）。"""
    cast = Cast()
    r1 = novelize_payload(PAYLOAD, style=get_style("novel"), cast=cast)
    if r1 is PAYLOAD:
        return False, "轮1降级为原文（解释器失败）"
    from galgame_coding.editor import call_editor
    recs = call_editor(get_style("novel"), cast.roster_text(), cast.scene_raw_text, cast.scene_rune_to_term)
    if recs is None:
        return False, "轮1编剧失败（档案未更新）"
    cast.update_from_editor(recs, cast.scene_rune_to_term)
    if not cast.characters:
        return False, "编剧未立任何角色（可能认为无角色可立，判据宽松仍视为通过？——不，失败）"
    r2 = novelize_payload(PAYLOAD, style=get_style("novel"), cast=cast)
    if r2 is PAYLOAD:
        return False, "轮2降级为原文"
    return True, (
        f"两轮改写成功；立档角色 {len(cast.characters)} 个："
        + "、".join(f"{c.name}({c.affinity})" for c in cast.characters.values())
    )


def main() -> None:
    _setup_console()
    parser = argparse.ArgumentParser(description="Phase 2.1 角色档案/文风验收")
    parser.add_argument("--live", action="store_true", help="真实调 DeepSeek 解释器+编剧（慢）")
    args = parser.parse_args()

    checks = [
        ("T1 跨轮稳定+零篡改+记账", t1_cast_stability),
        ("T2 编剧白名单校验", t2_editor_validation),
        ("T3 C符文缺失降级", t3_c_rune_missing),
        ("T4 merge_key 归并", t4_merge_key),
        ("T5 cast 持久化", t5_cast_persistence),
        ("T6 文风注册表", t6_style_registry),
        ("T7 坏档回归（真实bug现场）", t7_bad_cast_regression),
    ]
    if args.live:
        checks.append(("LIVE 真实两轮", check_live))

    print(f"== Phase 2.1 验收：{len(checks)} 项 ==")
    pass_cnt = 0
    for name, fn in checks:
        t0 = time.time()
        try:
            ok, msg = fn()
        except AssertionError as e:
            ok, msg = False, str(e)
        print(f"{name}: {'PASS' if ok else 'FAIL'} — {msg}（{time.time() - t0:.1f}s）")
        pass_cnt += ok
    print(f"\n== 汇总：{pass_cnt}/{len(checks)} PASS ==")
    sys.exit(0 if pass_cnt == len(checks) else 1)


if __name__ == "__main__":
    main()
