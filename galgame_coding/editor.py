"""编剧副 agent（Phase 2.1）：维护角色档案（形象名/人设/好感度）。

契约（Plan agent 审查定稿）：
- 输入：旧角色表 + 本场改写文本（回填前，符文可见）+ 符文对照表
  （rune → 原词，宿主本轮 mapping 的闭集白名单）
- 输出：JSON 数组 [{"runes": ["{{C1}}", "{{3}}"], "name": "...",
  "persona": "...", "affinity": 62}] —— 只给创意（形象名/人设/好感），
  id 与 aliases 由宿主从 rune 解析，编剧不自己填 id（避免编造/推断误差）。
  想合并两个符文为同一角色 → 放同一条记录里。

校验 fail-soft：编剧输出不进渲染路径，失败的唯一后果是沿用旧档案 +
一行提示（与解释器校验失败=降级原文、有可见后果的性质不同）。
"""

import json
import re
import subprocess
import sys

from .style import Style

# 解释器副 agent（全局工具链，见 ~/.claude/CLAUDE.md）
WEBAGENT = "C:/Users/qwe13/.claude/toolkit/webagent.py"
EDITOR_TIMEOUT = 60  # 秒；webagent 内部默认重试，这里只做外层兜底

_SYSTEM = """你是这款 galgame 的编剧与角色管理人，负责把剧本中的"角色"立起来、
养起来。玩家正在攻略这些角色，角色要言行一致、能成长、不能脸谱化。

输入分三段：当前角色表、本场改写文本（回填前，符文可见）、符文对照表
（符文对应的原词）。

任务：输出角色档案更新，纯 JSON 数组（不要任何额外说明）：
[{"runes": ["{{C1}}"], "name": "小石", "persona": "冷静可靠的数据库精灵，微毒舌", "affinity": 62}]

规则（必须全部遵守）：
1. runes：引用本场改写文本/对照表里真实出现的符文，原样书写（{{C1}}、{{3}}），
   不得编造对照表外的符文。**合并限同一实体的不同拼写**（大小写、版本号、
   缩写差异，如 sqlite3 与 SQLite）；不同技术概念、不同命令、不同参数、
   不同文件绝对禁止放进同一条记录的 runes——一条记录最多 3 个符文，
   宁缺毋滥
2. 立档标准：只给"有戏"的实体立角色——核心技术栈、反复出现、能承载剧情
   张力的概念；一次性工具名（如 sys.argv、os.path）、命令词（如 add/done/
   list）、参数名（如 --due）、文件路径、日期格式，一律不立档也不并入
   任何角色。别让角色泛滥，主角团 2-4 个最合适
3. 已在角色表的符文：维持其身份，可更新 persona 细节、按本场表现微调
   affinity；不得改名、不得并入其他角色
4. name：符合当前文风（{style_desc}）的形象名，1-20 字，与已有角色区分；
   首次登场的新角色必须取名（它就是玩家将攻略的角色）
5. persona：中性本质（性格/来历/口头禅），不写文风化台词，30-80 字
6. affinity：0-100。玩家与它合作顺利/它帮上忙 → +2~8；拖后腿/给玩家
   添麻烦 → -2~8；表现中立 → 不调整（省略该字段）。新角色缺省 50
7. 没提到的旧角色一律保留（不要删任何角色）
"""

_RUNE_RE = re.compile(r"^\{\{C?\d+\}\}$")


def _call_editor(prompt_text: str, system_prompt: str) -> str | None:
    """同步调 webagent.py（DeepSeek 网页版），返回其 --json stdout。

    失败（网络/凭证/超时/非零退出）返回 None，由调用方沿用旧档案。
    """
    cmd = [sys.executable, WEBAGENT, "ds", prompt_text, "--system", system_prompt, "--json"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=EDITOR_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _parse(raw: str) -> list | None:
    """解析 webagent --json 输出里的 {content}（剥代码块 + json.loads）。"""
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return None
    content = out.get("content") if isinstance(out, dict) else None
    if not isinstance(content, str) or not content.strip():
        return None
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", content).strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def _validated(records: list, valid_runes: set[str]) -> list[dict]:
    """逐条白名单校验：坏记录丢弃，过滤后 runes 为空则该条整体丢弃。"""
    out = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        runes = [
            r for r in rec.get("runes", [])
            if isinstance(r, str) and _RUNE_RE.match(r) and r in valid_runes
        ]
        if not runes:
            continue
        name = str(rec.get("name", "")).strip()[:20]
        if not name:
            continue
        persona = str(rec.get("persona", "")).strip().replace("\n", " ")[:300]
        aff = rec.get("affinity")
        affinity = None
        if isinstance(aff, int) and not isinstance(aff, bool):
            affinity = max(0, min(100, aff))
        out.append({"runes": runes, "name": name, "persona": persona, "affinity": affinity})
    return out


def call_editor(
    style: Style,
    roster_text: str,
    scene_raw_text: str,
    rune_to_term: dict[str, str],
) -> list[dict] | None:
    """调编剧副 agent 更新角色档案。

    scene_raw_text：本场改写文本（回填前，符文可见）；rune_to_term：
    本轮 mapping 的逆映射（含普通符文与角色符文，构成白名单）。
    失败/校验不过 → None（调用方沿用旧档案，打提示行，不阻塞）。
    """
    valid_runes = set(rune_to_term)
    parts = [
        f"【当前角色表】\n{roster_text or '（暂无角色）'}",
        f"【本场改写文本（回填前，符文可见）】\n{scene_raw_text}",
        "【符文对照表】\n" + "\n".join(
            f"{rune} = {term}" for rune, term in sorted(rune_to_term.items())
        ),
    ]
    system = _SYSTEM.replace("{style_desc}", style.description)
    raw = _call_editor("\n\n".join(parts), system)
    if raw is None:
        return None
    data = _parse(raw)
    if data is None:
        return None
    return _validated(data, valid_runes)
