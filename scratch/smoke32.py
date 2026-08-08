"""Phase 3.2 冒烟测试（临时，不提交）：monkeypatch 解释器，验证
1) system prompt 组装含 纪律段/前情/上一幕 且顺序固定
2) 写回契约记账（summary_delta/importance）
3) record_scene 更新上一幕（含玩家所选）
4) 回档 truncate 语义（story.truncate）
"""
import sys

sys.path.insert(0, "D:/github/just_for_fun")

import galgame_coding.novel as N
from galgame_coding.story import StoryMemory


def make_fake(raw_payload, system):
    """fake 解释器：记录 system，输出含全部三要素与写回字段的 JSON。"""
    def fake(raw, sys_prompt):
        fake.calls.append(sys_prompt)
        return (
            '{"content": "{\\"question\\": \\"{{1}} 的石碑在夜风中低语，我回想起了上一幕。\\",'
            ' \\"options\\": [{\\"label\\": \\"方案A\\", \\"detail\\": \\"【做法】用 {{1}}【代价】慢【回滚】删掉\\"},'
            ' {\\"label\\": \\"方案B\\", \\"detail\\": \\"【做法】用 {{1}}【代价】快【回滚】回退\\"}],'
            ' \\"summary_delta\\": \\"我站在石碑前，决定以 {{1}} 安放数据。\\", \\"importance\\": 2}"}'
        )
    fake.calls = []
    return fake


def main() -> None:
    story = StoryMemory()
    N._call_interpreter = make_fake(None, None)

    payload = {
        "question": "sqlite3 还是 json 来存数据？",
        "options": [
            {"label": "方案A：json", "detail": "【做法】用 json【代价】慢【回滚】删掉"},
            {"label": "方案B：sqlite3", "detail": "【做法】用 sqlite3【代价】快【回滚】回退"},
        ],
    }

    # --- 第一幕：无前情 ---
    out1 = N.novelize_payload(payload, story=story)
    sys1 = N._call_interpreter.calls[-1]
    assert "【剧本纪律】" in sys1  # 纪律段在
    # 首幕无记忆（动态注入段缺席；纪律段自身的"【前情】"字样不算）
    assert "本场必须接续它们" not in sys1 and "本场必须从此刻之后继续" not in sys1
    assert "【做法】" in out1["options"][0]["detail"]  # 结构校验通过（三要素）
    assert len(story.summaries) == 1 and story.summaries[0].importance == 2
    assert "石碑" in story.summaries[0].text  # summary_delta 记账

    print("STEP1 done")  # DEBUG
    # --- 玩家选择后：上一幕更新（符文形态！nonce 隔离） ---
    story.record_scene(1)
    assert "{{1}}" in story.prev_scene and "sqlite3" not in story.prev_scene
    assert "方案B" in story.prev_scene

    # --- 第二幕：前情 + 上一幕注入，顺序固定（纪律段在前，上幕最后） ---
    payload2 = {
        "question": "命令怎么解析？",
        "options": [
            {"label": "方案A：argparse", "detail": "【做法】用 argparse【代价】厚【回滚】回退"},
            {"label": "方案B：手写", "detail": "【做法】手写解析【代价】累【回滚】回退"},
        ],
    }
    out2 = N.novelize_payload(payload2, story=story)
    sys2 = N._call_interpreter.calls[-1]
    assert "【剧本纪律】" in sys2
    assert "本场必须接续它们" in sys2 and "我站在石碑前" in sys2  # 梗概注入
    assert "本场必须从此刻之后继续" in sys2 and "{{1}}" in sys2  # 上幕注入（符文形态）
    pos = [sys2.find(seg) for seg in ("【剧本纪律】", "本场必须接续它们", "本场必须从此刻之后继续")]
    assert pos == sorted(pos) and pos[0] < pos[1] < pos[2], f"注入顺序错位: {pos}"
    assert len(story.summaries) == 2

    # --- 滚动窗口：首条 + 最近 6 条 ---
    for i in range(6):
        story.record_summary(f"第 {i + 3} 幕摘要片段", 1)
    assert len(story.summaries) == 7  # 1 + 6

    # --- 回档 truncate：删第 3..end ---
    story.truncate(2)
    assert len(story.summaries) == 2
    story.truncate(0)
    assert story.summaries == [] and story.prev_scene == ""

    # --- fail-soft：summary_delta 坏格式不炸 ---
    N._call_interpreter = lambda raw, sys_prompt: (
        '{"content": "{\\"question\\": \\"{{1}} 之夜。\\", \\"options\\": '
        '[{\\"label\\": \\"A\\", \\"detail\\": \\"【做法】a【代价】b【回滚】c\\"}, '
        '{\\"label\\": \\"B\\", \\"detail\\": \\"【做法】d【代价】e【回滚】f\\"}], '
        '\\"summary_delta\\": 12345}"}'
    )
    out3 = N.novelize_payload(payload, story=story)
    assert out3["question"]  # 正常返回
    assert len(story.summaries) == 0  # 坏格式不记账

    # --- 降级轮零记账（2026-08-09 修复回归）：残留占位符 → 降级 → 不记账 ---
    N._call_interpreter = lambda raw, sys_prompt: (
        '{"content": "{\\"question\\": \\"{{1}} 之夜。\\", \\"options\\": '
        '[{\\"label\\": \\"A\\", \\"detail\\": \\"【做法】a{{9}}【代价】b【回滚】c\\"}, '
        '{\\"label\\": \\"B\\", \\"detail\\": \\"【做法】d【代价】e【回滚】f\\"}], '
        '\\"summary_delta\\": \\"本幕摘要。\\", \\"importance\\": 2}"}'
    )
    out4 = N.novelize_payload(payload, story=story)
    assert out4["question"] == payload["question"]  # 降级（{{9}} 不在 mapping，残留）
    assert len(story.summaries) == 0  # 降级轮零记账

    print("SMOKE OK")
    print("=== system 段顺序 ===")
    for seg in ("你是日式轻小说风格的叙事者", "【剧本纪律】", "【前情】", "【上一幕结尾】"):
        print(f"  {seg}: {seg in sys2}")


if __name__ == "__main__":
    main()
