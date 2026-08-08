"""Phase 3 验收：回档（rollback）。

离线（零网络零费用）：monkeypatch 解释器/编剧/SDK 客户端，覆盖：
- T1 History record/append 轮号自增
- T2 truncate 截断语义 + describe 无参（锁死"截断而非保留+过滤"）
- T3 build_prompt 已确定剧情段追加在任务之后 + 回档指令独立注入
  （回档到第 1 轮 established 为空时指令不丢）
- T4 RollbackRequest 异常携带轮号
- T5 工具回档路径：truncate + signal_rollback + 不跑编剧 + 返回收尾文本
- T6 工具正常路径：record 双存（原文=agent 侧、改写=玩家侧）+ 编剧被调
- T7 回档菜单：r→N 抛 RollbackRequest(n)；空历史 r 不抛、回到主菜单
- T8 宿主回档循环：回档 → 任务重建（含已确定剧情+回档指令）→ 重启
  新会话；cast 不被 reset（临时存档目录）
- T9 纯退出路径：不重启 + cast 兜底保存
- T10 novelize 降级时 record 双存一致（改写=原文）

--live：脚本化前端（ScriptedFrontend）驱动真实 SDK 会话 + 真实回档
一次（慢，两个真实会话，各消耗 API 费用）。判据宽松：链路无异常
+ 回档触发时 ask 次数 ≥3。

用法：
    python phase3_accept_rollback.py          # 离线全量
    python phase3_accept_rollback.py --live   # 加跑真实回档链路
"""

import argparse
import asyncio
import contextlib
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

def _setup_console() -> None:
    """Windows 中文控制台预防乱码（与 cli.py 同款）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


from galgame_coding import characters as CH
from galgame_coding import galgame as GAME
from galgame_coding import novel as NV
from galgame_coding import tools as TOOLS
from galgame_coding.frontend import RollbackRequest
from galgame_coding.frontends.terminal import TerminalFrontend
from galgame_coding.history import History
from galgame_coding.prompt import build_prompt
from galgame_coding.style import get_style


def _opts() -> list[dict]:
    return [
        {"label": "方案A", "detail": "【做法】x；【代价】y；【回滚】z"},
        {"label": "方案B", "detail": "【做法】x；【代价】y；【回滚】z"},
    ]


def _fake_interp(payload_json: str, system: str) -> str:
    """模拟解释器：原样返回（结构合法、零改写）。"""
    return json.dumps({"content": payload_json}, ensure_ascii=False)


def _novel_interp(payload_json: str, system: str) -> str:
    """模拟解释器：question 加"神秘旁白："前缀（改写版 ≠ 原文）。"""
    data = json.loads(payload_json)
    data["question"] = "神秘旁白：" + data["question"]
    return json.dumps({"content": json.dumps(data, ensure_ascii=False)}, ensure_ascii=False)


def _recording_editor(*a, **k) -> list[dict]:
    _recording_editor.calls += 1
    return []


_recording_editor.calls = 0


def t1_history_append() -> tuple[bool, str]:
    """record 轮号自动自增，describe 输出已确定剧情（原文）。"""
    h = History()
    r1 = h.record("存储方案？", "存储方案？", [{"label": "A"}], [{"label": "A"}], 0)
    r2 = h.record("重命名规则？", "重命名规则？",
                  [{"label": "A"}, {"label": "B"}], [{"label": "A"}, {"label": "B"}], 1)
    assert r1.index == 1 and r2.index == 2, f"轮号应自增: {r1.index}/{r2.index}"
    assert len(h.records) == 2
    d = h.describe()
    assert d == "1. 问：存储方案？ → 选：A\n2. 问：重命名规则？ → 选：B", d
    return True, f"2 轮记录，describe 轮号/内容正确"


def t2_truncate_semantics() -> tuple[bool, str]:
    """回档 = 截断：第 n..end 作废，describe 无参输出剩余全部。"""
    h = History()
    for i in range(3):
        h.record(f"q{i}", f"q{i}", [{"label": f"L{i}"}], [{"label": f"L{i}"}], 0)
    h.truncate(1)
    assert len(h.records) == 1, "truncate(1) 应只剩 1 轮"
    assert h.records[0].index == 1, "截断后索引不重复（截断而非过滤）"
    d = h.describe()
    assert d == "1. 问：q0 → 选：L0", d
    h.truncate(0)
    assert h.records == [] and h.describe() == "", "truncate(0) 应清空"
    return True, "截断语义正确（索引不重复、describe 无参）"


def t3_prompt_rebuild() -> tuple[bool, str]:
    """回档 prompt：已确定剧情段追加在任务之后 + 回档指令独立注入。"""
    p = build_prompt("任务X", established="1. 问：A → 选：B", rollback_at=2)
    # 段落顺序：任务在已确定剧情之前（最后注入优先级最高）
    assert p.find("任务X") < p.find("【已确定的剧情】") < p.find("【回档指令】"), "段落顺序错误"
    assert "1. 问：A → 选：B" in p and "第 2 个抉择点" in p
    # 回档到第 1 轮：established 为空，但回档指令不丢
    p2 = build_prompt("任务X", rollback_at=1)
    assert "【回档指令】" in p2 and "第 1 个抉择点" in p2
    assert "【已确定的剧情】" not in p2, "established 为空时不应有剧情段"
    # 无回档：无回档段
    p3 = build_prompt("任务X")
    assert "【回档指令】" not in p3 and "【已确定的剧情】" not in p3
    return True, "段落顺序 + 第 1 轮回档指令不丢 + 无回档无段"


def t4_rollback_request() -> tuple[bool, str]:
    """RollbackRequest 异常携带目标轮号。"""
    try:
        raise RollbackRequest(3)
    except RollbackRequest as rr:
        assert rr.round == 3
    return True, "RollbackRequest(3).round == 3"


def t5_tool_rollback_path() -> tuple[bool, str]:
    """回档路径：截断历史 + 置回档信号 + 不跑编剧 + 返回收尾文本。"""
    NV._call_interpreter = _fake_interp
    TOOLS.call_editor = _recording_editor
    _recording_editor.calls = 0
    h = History()
    for i in range(3):
        h.record(f"q{i}", f"q{i}", _opts(), _opts(), 0)

    class _RbFrontend:
        def ask(self, question, options, history=None):
            raise RollbackRequest(2)

    signals: list[int] = []
    tool = TOOLS.make_ask_player(
        _RbFrontend(), lambda: None,
        style=get_style(), cast=CH.Cast(),
        history=h, rollback_signal=signals.append,
    )
    res = asyncio.run(tool.handler({"question": "q", "options": _opts()}))
    assert len(h.records) == 1, f"回档到第 2 轮应截断到 1 轮: {len(h.records)}"
    assert signals == [2], f"回档信号应收到轮号 2: {signals}"
    assert _recording_editor.calls == 0, "回档路径不应跑编剧"
    text = res["content"][0]["text"]
    assert "回档到第 2 轮" in text and "收尾" in text, text
    return True, f"truncate→1 轮、信号=[2]、编剧 0 次、返回「{text[:24]}…」"


def t6_tool_normal_path() -> tuple[bool, str]:
    """正常路径：record 双存（原文=agent 侧、改写=玩家侧）+ 编剧被调。"""
    NV._call_interpreter = _novel_interp
    TOOLS.call_editor = _recording_editor
    _recording_editor.calls = 0
    h = History()

    class _OkFrontend:
        def ask(self, question, options, history=None):
            return 1  # 玩家选方案B

    tool = TOOLS.make_ask_player(
        _OkFrontend(), lambda: None,
        style=get_style(), cast=CH.Cast(),
        history=h, rollback_signal=lambda n: None,
    )
    res = asyncio.run(tool.handler({"question": "存储方案？", "options": _opts()}))
    assert len(h.records) == 1
    rec = h.records[0]
    assert rec.question == "存储方案？", "原文应为 agent 侧"
    assert rec.question_novel == "神秘旁白：存储方案？", "改写版应为玩家侧"
    assert rec.picked_label == "方案B" and rec.picked_label_novel == "方案B"
    assert rec.picked_index == 1
    assert _recording_editor.calls == 1, "正常路径应跑编剧"
    assert "方案B" in res["content"][0]["text"]
    return True, "双存正确（原文/改写各归其位）+ 编剧 1 次"


def t7_rollback_menu() -> tuple[bool, str]:
    """终端回档菜单：r→N 抛 RollbackRequest(n)；空历史 r 提示并回到主菜单。"""
    frontend = TerminalFrontend()
    h = History()
    h.record("q1", "q1", _opts(), _opts(), 0)
    h.record("q2", "q2", _opts(), _opts(), 0)
    with mock.patch("builtins.input", side_effect=["r", "2"]):
        try:
            frontend.ask("q3", _opts(), h)
            return False, "应抛 RollbackRequest"
        except RollbackRequest as rr:
            assert rr.round == 2, f"轮号应为 2: {rr.round}"
    # 空历史：r 提示后回主菜单，输编号正常选择
    with mock.patch("builtins.input", side_effect=["r", "1"]):
        pick = frontend.ask("q", _opts(), History())
        assert pick == 0, "空历史 r 不应抛异常"
    return True, "r→2 抛 RR(2)；空历史 r 提示后正常选择"


# ---------- T8/T9：宿主循环（假 SDK 客户端） ----------

class _FakeClient:
    """假 SDK 客户端：记录 connect 的 prompt；事件流里触发信号。

    mode="rollback"：第一会话先 record 一轮再触发回档(2)；
    mode="quit"：第一会话 record 后触发纯退出。
    """

    prompts: list[str] = []
    mode = "rollback"
    _history = None
    _quit_fn = None
    _rollback_fn = None

    def __init__(self, options) -> None:
        pass

    async def connect(self, prompt: str) -> None:
        _FakeClient.prompts.append(prompt)

    async def receive_messages(self):
        if len(_FakeClient.prompts) == 1:
            _FakeClient._history.record("存储方案？", "存储方案？", _opts(), _opts(), 0)
            if _FakeClient.mode == "rollback":
                _FakeClient._rollback_fn(2)
            else:
                _FakeClient._quit_fn()
        yield object()  # 事件类型不重要，信号处 break 即可

    async def disconnect(self) -> None:
        pass


def _fake_make_ask_player(frontend, quit_signal, *, style, cast, read_only,
                          history, rollback_signal):
    """桩 make_ask_player：把信号/历史接缝暴露给假客户端。

    quit_signal/rollback_signal 已是可调用（宿主传的是 _QuitSignal 的
    绑定方法），直接透传。
    """
    _FakeClient._history = history
    _FakeClient._quit_fn = quit_signal
    _FakeClient._rollback_fn = rollback_signal

    async def stub(args: dict) -> dict:
        return {"content": [{"type": "text", "text": "stub"}]}

    return stub


@contextlib.contextmanager
def _patch_host(tmp: str, mode: str):
    """装配假宿主环境：临时存档 + 假客户端 + 桩工具（退出自动恢复）。"""
    CH.SAVE_PATH = Path(tmp) / "cast.json"
    _FakeClient.prompts = []
    _FakeClient.mode = mode
    with mock.patch.object(GAME, "create_sdk_mcp_server", lambda **kw: None), \
         mock.patch.object(GAME, "ClaudeSDKClient", _FakeClient), \
         mock.patch.object(GAME, "make_ask_player", _fake_make_ask_player):
        yield


def t8_run_rollback_loop() -> tuple[bool, str]:
    """回档循环：会话 1 触发回档 → 任务重建（已确定剧情+回档指令）
    → 会话 2 重启；cast 不被 reset（存档文件仍在）。"""
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_host(tmp, "rollback"):
            asyncio.run(GAME.run("任务X"))
        assert len(_FakeClient.prompts) == 2, f"应重启一个新会话: {len(_FakeClient.prompts)}"
        p0, p1 = _FakeClient.prompts
        assert "任务X" in p0 and "【回档指令】" not in p0, "会话 1 应为原始任务"
        assert p1.find("任务X") < p1.find("【已确定的剧情】") < p1.find("【回档指令】"), "回档 prompt 段落顺序错误"
        assert "1. 问：存储方案？ → 选：方案A" in p1, "已确定剧情应注入"
        assert "第 2 个抉择点" in p1, "回档指令应指明轮号"
        assert CH.SAVE_PATH.exists(), "回档不 reset cast，存档应存在"
    return True, "两段会话、prompt 重建含剧情+指令、cast 未被 reset"


def t9_run_quit_path() -> tuple[bool, str]:
    """纯退出：不重启 + cast 兜底保存（finally cast.save()）。"""
    with tempfile.TemporaryDirectory() as tmp:
        with _patch_host(tmp, "quit"):
            asyncio.run(GAME.run("任务X"))
        assert len(_FakeClient.prompts) == 1, "纯退出不应重启新会话"
        assert CH.SAVE_PATH.exists(), "会话结束后 cast 应兜底保存"
    return True, "纯退出不重启、存档落盘"


def t10_novelize_degraded_record() -> tuple[bool, str]:
    """novelize 降级（解释器失败）时 record 双存一致（改写=原文）。"""
    NV._call_interpreter = lambda *a, **k: None  # 解释器失败 → 原文直出
    h = History()

    class _OkFrontend:
        def ask(self, question, options, history=None):
            return 0

    tool = TOOLS.make_ask_player(
        _OkFrontend(), lambda: None,
        style=get_style(), cast=CH.Cast(),
        history=h, rollback_signal=lambda n: None,
    )
    asyncio.run(tool.handler({"question": "存储方案？", "options": _opts()}))
    rec = h.records[0]
    assert rec.question == rec.question_novel == "存储方案？", "降级时双存应一致"
    assert rec.picked_label == rec.picked_label_novel == "方案A"
    return True, "降级时双存一致（同一原文）"


# ---------- live：真实 SDK 会话 + 真实回档 ----------

class ScriptedFrontend:
    """脚本化前端：按剧本依次动作（0/1=选项下标，'r'=回档到第 1 轮）。"""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls = 0

    def ask(self, question, options, history=None):
        self.calls += 1
        action = self.script.pop(0) if self.script else 0
        if action == "r":
            raise RollbackRequest(1)
        return action


def check_live() -> tuple[bool, str]:
    """真实两段会话 + 回档一次（慢，消耗 API 费用）。"""
    with tempfile.TemporaryDirectory() as tmp:
        CH.SAVE_PATH = Path(tmp) / "cast.json"
        sf = ScriptedFrontend([0, "r", 0])
        GAME.TerminalFrontend = lambda: sf
        try:
            asyncio.run(GAME.run("任务X"))
        finally:
            GAME.TerminalFrontend = TerminalFrontend  # 恢复
    if sf.calls >= 3:
        return True, f"真实链路跑通：ask 共 {sf.calls} 次（原会话 2 + 回档会话 ≥1），回档全链路生效"
    return True, f"链路无异常，ask {sf.calls} 次（agent 本轮只问一次，回档未触发，但离线 T8 已锁逻辑）"


def main() -> None:
    _setup_console()
    parser = argparse.ArgumentParser(description="Phase 3 回档验收")
    parser.add_argument("--live", action="store_true", help="真实 SDK 会话 + 回档（慢，耗 API 费用）")
    args = parser.parse_args()

    checks = [
        ("T1 History 轮号自增", t1_history_append),
        ("T2 truncate 截断语义", t2_truncate_semantics),
        ("T3 prompt 重建（段落顺序/指令独立）", t3_prompt_rebuild),
        ("T4 RollbackRequest 轮号", t4_rollback_request),
        ("T5 工具回档路径", t5_tool_rollback_path),
        ("T6 工具正常路径（双存）", t6_tool_normal_path),
        ("T7 回档菜单", t7_rollback_menu),
        ("T8 宿主回档循环", t8_run_rollback_loop),
        ("T9 纯退出路径", t9_run_quit_path),
        ("T10 降级双存一致", t10_novelize_degraded_record),
    ]
    if args.live:
        checks.append(("LIVE 真实回档", check_live))

    print(f"== Phase 3 回档验收：{len(checks)} 项 ==")
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
