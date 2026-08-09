"""快速验证（2026-08-09）：角色教学条件化 + 点卯回填/记账。

  S1. cast=None（Phase 2 精确行为）→ system 无 "{{C"
  S2. 空 Cast（--reset-cast 新周目）→ system 无 "{{C"
  S3. 有角色 + 载荷含角色词 → 教学段 + 【角色表】 + 角色纪律
  S4. 有角色但载荷不含角色词 → 仍注入教学 + roster（解释器可点卯）
  S5. 点卯：解释器让未播种的 {{C1}} 冒头 → 回填原词、无降级、记账出场
  S6. 必现段：缺席 ≥2 幕 → system 注入【本场必现】；解释器让角色出场
      → 记账 + 缺席清零；出场后不再注入

零网络零费用：monkeypatch _call_interpreter 捕获 system 原样返回。
"""
import json
import re
import sys

sys.path.insert(0, "D:/github/just_for_fun")
import galgame_coding.novel as novel
from galgame_coding.characters import Cast, Character

captured = {}


def fake_call(text: str, system: str) -> str:
    captured["system"] = system
    data = json.loads(text)
    data["summary_delta"] = "测试摘要"
    data["importance"] = 2
    if captured.get("point_卯"):
        # 点卯：改写文本里让 {{C1}} 出场（未播种符文）
        data["question"] = "{{C1}} 在一旁轻轻开口：「别急，数据的事交给我。」" + data["question"]
    return json.dumps({"content": json.dumps(data, ensure_ascii=False)}, ensure_ascii=False)


novel._call_interpreter = fake_call

PAYLOAD = {
    "question": "项目骨架怎么定？SQLite 还是 JSON？",
    "options": [
        {"label": "方案A：SQLite", "detail": "【做法】用 SQLite 存 todos。【代价】部署略重。【回滚】删库文件。"},
        {"label": "方案B：JSON", "detail": "【做法】用 JSON 存 todos。【代价】并发弱。【回滚】换回 SQLite。"},
    ],
}
PAYLOAD_NO_CHAR = {
    "question": "输出格式怎么定？",
    "options": [
        {"label": "方案A：表格", "detail": "【做法】用表格排版。【代价】宽屏依赖。【回滚】改回纯文本。"},
        {"label": "方案B：纯文本", "detail": "【做法】用纯文本排版。【代价】信息密度低。【回滚】改回表格。"},
    ],
}


def seeded_cast() -> Cast:
    cast = Cast()
    cast.characters[1] = Character(n=1, id="SQLite", name="小石", persona="数据库精灵", affinity=60, meetings=0, last_line="")
    cast.term_placeholders["SQLite"] = "{{C1}}"
    cast._ph_to_n["{{C1}}"] = 1
    return cast


def run(name: str, payload: dict, cast, want_c: bool, point_卯: bool = False) -> tuple[bool, str]:
    captured.clear()
    captured["point_卯"] = point_卯
    out = novel.novelize_payload(json.loads(json.dumps(payload)), cast=cast)
    sys_ = captured["system"]
    has_c = "{{C" in sys_
    ok = has_c is want_c
    note = ""
    if point_卯:
        text = json.dumps(out, ensure_ascii=False)
        ok = ok and out != payload and "SQLite" in text
        ch = cast._find_by_key("SQLite")
        ok = ok and ch.meetings == 1 and ch.absent_rounds == 0
        note = f" 点卯回填={'SQLite' in text} 记账={ch.meetings} 缺席={ch.absent_rounds}"
        if not ok:
            note += f" (system含C={has_c}, 降级={out == payload})"
    extra = ""
    if want_c and not point_卯:
        extra = f" 教学段={'{{C数字}} 是已在本剧本立档的角色' in sys_} 角色表={'【角色表】' in sys_}"
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: system含{{{{C}}={has_c} (len={len(sys_)}){extra}{note}")
    return ok


def run_s6() -> bool:
    """必现段：缺席计数 → 注入；出场 → 记账清零；出场后不再注入。"""
    cast = seeded_cast()
    # 两幕缺席（novelize 每幕 tick_absent +1）
    for _ in range(2):
        captured.clear()
        captured["point_卯"] = False
        out = novel.novelize_payload(json.loads(json.dumps(PAYLOAD_NO_CHAR)), cast=cast)
        assert "SQLite" not in json.dumps(out, ensure_ascii=False), "缺席幕不应回填"
    # 第三幕：缺席 2 → 必现注入
    captured.clear()
    captured["point_卯"] = False
    novel.novelize_payload(json.loads(json.dumps(PAYLOAD_NO_CHAR)), cast=cast)
    sys_ = captured["system"]
    due_ok = "【本场必现】" in sys_ and "{{C1}}" in sys_ and re.search(r"已连续 \d+ 幕未登场", sys_) is not None
    # 第四幕：解释器让 {{C1}} 出场 → 记账 + 清零
    captured.clear()
    captured["point_卯"] = True
    out = novel.novelize_payload(json.loads(json.dumps(PAYLOAD_NO_CHAR)), cast=cast)
    ch = cast._find_by_key("SQLite")
    ok = due_ok and ch.meetings == 1 and ch.absent_rounds == 0
    # 第五幕：缺席 1（刚出场）→ 不再注入必现
    captured.clear()
    captured["point_卯"] = False
    novel.novelize_payload(json.loads(json.dumps(PAYLOAD_NO_CHAR)), cast=cast)
    sys5 = captured["system"]
    ok = ok and "【本场必现】" not in sys5 and ch.absent_rounds == 1
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] S6 必现注入+缺席联动: 注入={due_ok} 记账={ch.meetings} 缺席={ch.absent_rounds}")
    return ok


results = []
results.append(run("S1 cast=None", PAYLOAD, None, want_c=False))
results.append(run("S2 空Cast新周目", PAYLOAD, Cast(), want_c=False))
results.append(run("S3 有角色+词在载荷", PAYLOAD, seeded_cast(), want_c=True))
results.append(run("S4 有角色但未播种", PAYLOAD_NO_CHAR, seeded_cast(), want_c=True))
results.append(run("S5 点卯回填+记账", PAYLOAD_NO_CHAR, seeded_cast(), want_c=True, point_卯=True))
results.append(run_s6())

print(f"\n{sum(results)}/6 通过")
sys.exit(0 if all(results) else 1)
