"""Phase 3.2 验收：剧情记忆（story.py）+ 回档联动。

离线（零网络零费用）：monkeypatch 解释器，覆盖：
- T1 system prompt 组装：模板→纪律→前情→上一幕 顺序固定，首幕无记忆
- T2 上幕接续：record_scene 提交含玩家所选、符文形态（nonce 隔离）
- T3 summary 记账 + importance 钳制（-5→0 / 9→3 / 非整数→0 / bool→0）
- T4 滚动窗口：首条全局锚点 + 最近 6 条
- T5 fail-soft：坏格式/空白/超长截断 不炸不记账
- T6 降级轮零记账（解释器失败 + 残留占位符两种降级路径）
- T7 回档截断 + 降级轮对齐（2026-08-09 核心回归）：分支点后含降级轮
  时，作废分支的摘要/场景必须清除、上一幕恢复为分支点锚点、
  当轮 pending 不泄漏、新会话轮号与 History 重新对齐
- T8 工具联动：begin_round 每轮占号、正常路径 record_scene 提交所选
- T9 载荷结构回归：三要素齐全、选项数一致、回填后技术名词原样

用法：
    python phase32_accept_story.py   # 离线全量
"""

import asyncio
import json
import sys
import time


def _setup_console() -> None:
    """Windows 中文控制台预防乱码（与 cli.py 同款）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


from galgame_coding import novel as NV
from galgame_coding import tools as TOOLS
from galgame_coding.frontend import RollbackRequest
from galgame_coding.history import History
from galgame_coding.story import SUMMARY_MAX_LEN, StoryMemory
from galgame_coding.style import get_style


def _payload(question: str, opt_labels: list[str]) -> dict:
    return {
        "question": question,
        "options": [
            {"label": l, "detail": "【做法】x；【代价】y；【回滚】z"} for l in opt_labels
        ],
    }


class _Recorder:
    """可编程解释器替身：记录每次的 system；plan 里 "fail" = 降级。

    成功时：question 加"神秘旁白："前缀（改写版 ≠ 原文）+ 写回契约
    字段（summary_delta 用符文形态——fake 只见过掩码文本，天然隔离）。
    """

    def __init__(self, plan: list[str] | None = None) -> None:
        self.plan = list(plan or [])
        self.systems: list[str] = []

    def __call__(self, payload_json: str, system: str) -> str | None:
        self.systems.append(system)
        if self.plan and self.plan.pop(0) == "fail":
            return None
        data = json.loads(payload_json)
        data["question"] = "神秘旁白：" + data["question"]
        data["summary_delta"] = "摘要：" + data["question"]
        data["importance"] = 2
        return json.dumps({"content": json.dumps(data, ensure_ascii=False)}, ensure_ascii=False)


class _Pick:
    """前端替身：每次都选固定下标。"""

    def __init__(self, idx: int) -> None:
        self.idx = idx

    def ask(self, question, options, history=None) -> int:
        return self.idx


class _RbFrontend:
    """前端替身：前 after 次选 0，之后抛 RollbackRequest(target)。"""

    def __init__(self, after: int, target: int) -> None:
        self.after, self.target, self.calls = after, target, 0

    def ask(self, question, options, history=None) -> int:
        self.calls += 1
        if self.calls > self.after:
            raise RollbackRequest(self.target)
        return 0


def t1_injection_order() -> tuple[bool, str]:
    """system prompt：模板→纪律→前情→上一幕 顺序固定；首幕无记忆。"""
    NV._call_interpreter = _Recorder()
    story = StoryMemory()
    NV.novelize_payload(_payload("sqlite3 还是 json 来存数据？", ["方案A", "方案B"]), story=story)
    sys1 = NV._call_interpreter.systems[-1]
    assert "【剧本纪律】" in sys1, "纪律段应在"
    assert "本场必须接续它们" not in sys1, "首幕无前情"
    assert "本场必须从此刻之后继续" not in sys1, "首幕无上一幕"
    # 第二幕：先提交第一幕，再改写——前情 + 上一幕 都注入且顺序固定
    story.record_scene(0)
    NV.novelize_payload(_payload("命令怎么解析？", ["方案A", "方案B"]), story=story)
    sys2 = NV._call_interpreter.systems[-1]
    assert "本场必须接续它们" in sys2 and "摘要：" in sys2, "梗概注入"
    assert "本场必须从此刻之后继续" in sys2 and "神秘旁白" in sys2, "上一幕注入"
    pos = [sys2.find(seg) for seg in
           ("你是日式轻小说风格的叙事者", "【剧本纪律】", "本场必须接续它们", "本场必须从此刻之后继续")]
    assert pos == sorted(pos) and all(p >= 0 for p in pos), f"注入顺序错位: {pos}"
    return True, "顺序固定（模板→纪律→前情→上幕），首幕无记忆"


def t2_scene_continuation() -> tuple[bool, str]:
    """上幕接续：record_scene 含玩家所选、符文形态（nonce 隔离）。"""
    NV._call_interpreter = _Recorder()
    story = StoryMemory()
    h = History()
    tool = TOOLS.make_ask_player(_Pick(1), lambda: None, style=get_style(),
                                 history=h, story=story)
    asyncio.run(tool.handler(_payload("sqlite3 还是 json？", ["方案A：json", "方案B：sqlite3"])))
    assert len(story.summaries) == 1 and story.summaries[0].round == 1, "第一幕记账"
    assert "{{1}}" in story.prev_scene, "上一幕应为符文形态"
    assert "sqlite3" not in story.prev_scene, "nonce 隔离：上一幕不得含原词"
    assert "方案B" in story.prev_scene, "上一幕应含玩家所选"
    assert story._scenes[0].round == 1 and story._scenes[0].text == story.prev_scene, "场景按轮存档"
    return True, "上一幕 = 符文形态 + 玩家所选，场景按轮存档"


def t3_summary_accounting() -> tuple[bool, str]:
    """summary 记账 + importance 钳制（越界/非整数/bool 全钳到合法域）。"""
    story = StoryMemory()
    story.begin_round()
    story.record_summary("  第一幕摘要  ", 2)
    story.record_summary("   ", 9)           # 空白 → 忽略
    story.record_summary("第二幕摘要", -5)    # 钳制 → 0
    story.record_summary("第三幕摘要", 9)     # 钳制 → 3
    story.record_summary("第四幕摘要", "x")   # 非整数 → 0
    story.record_summary("第五幕摘要", True)  # bool 是 int 子类 → 0（显式排除）
    assert [e.importance for e in story.summaries] == [2, 0, 3, 0, 0], \
        [e.importance for e in story.summaries]
    assert all(e.round == 1 for e in story.summaries), "条目携带轮号"
    return True, "importance [2,0,3,0,0]，空白忽略，轮号正确"


def t4_rolling_window() -> tuple[bool, str]:
    """滚动窗口：首条全局锚点 + 最近 6 条。"""
    story = StoryMemory()
    for i in range(1, 11):
        story.record_summary(f"第 {i} 幕", 1)
    assert len(story.summaries) == 7, f"应 7 条: {len(story.summaries)}"
    assert story.summaries[0].text == "第 1 幕", "首条全局锚点"
    assert [e.text for e in story.summaries[1:]] == [f"第 {i} 幕" for i in range(5, 11)], \
        "最近 6 条"
    return True, "首条锚点 + 第 5..10 幕共 7 条"


def t5_fail_soft() -> tuple[bool, str]:
    """fail-soft：坏格式/空白/超长不炸不记账。"""
    story = StoryMemory()
    story.begin_round()
    story.record_summary("正常摘要", 2)
    story.record_summary(12345)          # 非字符串 → 忽略
    story.record_summary("")             # 空白 → 忽略
    story.record_summary("长" * (SUMMARY_MAX_LEN + 50), 1)  # 超长截断
    assert len(story.summaries) == 2, "坏格式不记账"
    assert len(story.summaries[1].text) == SUMMARY_MAX_LEN, "超长截断到 120 字"

    def _bad_delta(payload_json: str, system: str) -> str:
        data = json.loads(payload_json)
        data["summary_delta"] = 12345  # 解释器输出坏格式写回字段
        return json.dumps({"content": json.dumps(data, ensure_ascii=False)}, ensure_ascii=False)

    NV._call_interpreter = _bad_delta
    out = NV.novelize_payload(_payload("sqlite3 存？", ["A", "B"]), story=story)
    assert out["question"], "坏格式写回字段不炸渲染路径"
    assert len(story.summaries) == 2, "坏格式写回字段不记账"
    return True, "坏格式/空白/超长全部静默处理"


def t6_degraded_zero_accounting() -> tuple[bool, str]:
    """降级轮零记账：解释器失败 + 残留占位符两种降级都不得记账。"""
    NV._call_interpreter = _Recorder(["ok", "fail"])
    story = StoryMemory()
    h = History()
    tool = TOOLS.make_ask_player(_Pick(0), lambda: None, style=get_style(),
                                 history=h, story=story)
    asyncio.run(tool.handler(_payload("存储方案？", ["A", "B"])))
    asyncio.run(tool.handler(_payload("命令解析？", ["A", "B"])))  # 第 2 轮 fail
    assert len(story.summaries) == 1, "解释器失败轮不记账"
    assert story.prev_scene == story._scenes[0].text, "降级轮上一幕不动"
    assert story._round_no == 2, "降级轮占号（保对齐）"

    def _leftover(payload_json: str, system: str) -> str:
        data = json.loads(payload_json)
        data["options"][0]["detail"] += " 遗留{{9}}"  # 自造不在 mapping 的符文
        return json.dumps({"content": json.dumps(data, ensure_ascii=False)}, ensure_ascii=False)

    NV._call_interpreter = _leftover
    asyncio.run(tool.handler(_payload("输出格式？", ["A", "B"])))  # 第 3 轮残留占位符
    assert len(story.summaries) == 1, "残留占位符降级也不记账"
    assert story.prev_scene == story._scenes[0].text, "残留占位符降级轮上一幕不动"
    return True, "两种降级路径均零记账、上一幕不动、轮号照常占"


def t7_rollback_alignment() -> tuple[bool, str]:
    """回档截断 + 降级轮对齐（核心回归）：作废分支全清除、上一幕恢复
    分支点锚点、pending 不泄漏、新会话轮号重新对齐。

    剧本：轮 1 成功、轮 2 降级、轮 3 成功、轮 4 成功（ask 期间回档到
    第 3 轮，keep=2）。计数截断会错位：轮 3 的摘要/上一幕属于作废分支
    但轮号 ≤ 当前轮，按数量截断删不掉——必须按轮号过滤。
    """
    NV._call_interpreter = _Recorder(["ok", "fail", "ok", "ok"])
    story = StoryMemory()
    h = History()
    tool = TOOLS.make_ask_player(_RbFrontend(3, 3), lambda: None, style=get_style(),
                                 history=h, story=story)
    for i in range(4):
        asyncio.run(tool.handler(_payload(f"第 {i + 1} 问？", ["A", "B"])))

    assert len(h.records) == 2, f"历史应截断到 2 轮: {len(h.records)}"
    assert [e.round for e in story.summaries] == [1], \
        f"作废分支摘要（轮 3/4）应清除: {[e.round for e in story.summaries]}"
    assert [s.round for s in story._scenes] == [1], \
        f"作废分支场景应清除: {[s.round for s in story._scenes]}"
    anchor = story.prev_scene
    assert "第 1 问" in anchor, "上一幕应恢复为分支点锚点（第 1 幕），而非作废分支的上一幕"
    assert story._pending_question is None, "当轮（第 4 问）未提交素材应清空"
    assert story._round_no == 2, f"轮号应重置为 keep=2: {story._round_no}"

    # 新会话重玩第 3 轮：先降级——旧 pending 不得泄漏进上一幕
    NV._call_interpreter = _Recorder(["fail"])
    tool2 = TOOLS.make_ask_player(_Pick(0), lambda: None, style=get_style(),
                                  history=h, story=story)
    asyncio.run(tool2.handler(_payload("第 3 问（重玩）？", ["A", "B"])))
    assert story.prev_scene == anchor, "降级轮不得用旧 pending 覆盖上一幕（泄漏）"
    assert [e.round for e in story.summaries] == [1], "降级轮不记账"
    assert story._round_no == 3, "降级轮占号（新会话第 3 轮）"

    # 新会话重玩第 4 轮：成功——轮号与 History 重新对齐
    NV._call_interpreter = _Recorder(["ok"])
    asyncio.run(tool2.handler(_payload("第 4 问（重玩）？", ["A", "B"])))
    assert [e.round for e in story.summaries] == [1, 4], \
        f"新会话条目轮号应与 History 对齐: {[e.round for e in story.summaries]}"
    assert h.records[3].index == 4, f"History 轮号应到 4: {h.records[3].index}"
    assert story._round_no == 4, "轮号与 History 同步推进"
    return True, "作废分支摘要/场景全清除、上一幕恢复锚点、pending 不泄漏、轮号重新对齐"


def t8_tool_wiring() -> tuple[bool, str]:
    """工具联动正常路径：begin_round 每轮占号 + record_scene 提交所选。"""
    NV._call_interpreter = _Recorder()
    story = StoryMemory()
    h = History()

    class _PickSeq:
        def __init__(self, seq: list[int]) -> None:
            self.seq = list(seq)

        def ask(self, question, options, history=None) -> int:
            return self.seq.pop(0)

    tool = TOOLS.make_ask_player(_PickSeq([0, 1]), lambda: None, style=get_style(),
                                 history=h, story=story)
    asyncio.run(tool.handler(_payload("存储方案？", ["方案A", "方案B"])))
    asyncio.run(tool.handler(_payload("命令解析？", ["方案A", "方案B"])))
    assert story._round_no == 2, "每轮占号"
    assert [e.round for e in story.summaries] == [1, 2], "条目轮号递增"
    assert "方案B" in story.prev_scene, "第二幕应含玩家所选（下标 1）"
    assert len(h.records) == 2 and h.records[1].index == 2, "History 同步"
    return True, "begin_round 每轮占号 + record_scene 提交所选"


def t9_payload_structure() -> tuple[bool, str]:
    """载荷结构回归：三要素齐全、选项数一致、回填后技术名词原样。"""
    NV._call_interpreter = _Recorder()
    payload = {
        "question": "用 sqlite3 还是 JSON 存数据？",
        "options": [
            {"label": "方案A：sqlite3", "detail": "【做法】用 sqlite3 建表；【代价】慢；【回滚】删库重建"},
            {"label": "方案B：JSON 文件", "detail": "【做法】写入 todos.json；【代价】乱；【回滚】覆盖"},
        ],
    }
    out = NV.novelize_payload(payload)
    assert out["question"] != payload["question"], "已改写"
    assert len(out["options"]) == 2, "选项数一致"
    for src, dst in zip(payload["options"], out["options"]):
        assert dst["label"] and dst["detail"], "字段非空"
        for tag in ("【做法】", "【代价】", "【回滚】"):
            assert tag in dst["detail"], f"缺 {tag}"
        assert dst["detail"] == src["detail"], "回填后 detail 应与原文逐字一致"
        assert dst["label"] == src["label"], "回填后 label 应与原文逐字一致"
    return True, "三要素齐全、选项数一致、技术名词回填原样"


def main() -> None:
    _setup_console()
    checks = [
        ("T1 注入顺序（模板→纪律→前情→上幕）", t1_injection_order),
        ("T2 上幕接续（玩家所选，符文形态）", t2_scene_continuation),
        ("T3 summary 记账 + importance 钳制", t3_summary_accounting),
        ("T4 滚动窗口（首条锚点 + 最近 6 条）", t4_rolling_window),
        ("T5 fail-soft（坏格式/空白/超长）", t5_fail_soft),
        ("T6 降级轮零记账（失败 + 残留占位符）", t6_degraded_zero_accounting),
        ("T7 回档截断 + 降级轮对齐（核心回归）", t7_rollback_alignment),
        ("T8 工具联动（begin_round + record_scene）", t8_tool_wiring),
        ("T9 载荷结构回归（三要素/回填原样）", t9_payload_structure),
    ]
    print(f"== Phase 3.2 剧情记忆验收：{len(checks)} 项 ==")
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
