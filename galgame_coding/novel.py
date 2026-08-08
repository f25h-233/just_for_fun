"""轻小说化（Phase 2）：把 ask_player 的载荷改写成日轻文本。

nonce 占位符方案（项目记忆定稿，保证"关键名词可人格化但词不能变"）：
1. 宿主从载荷提取关键名词（技术名词/路径/命令）→ 替换为 {{N}} 占位符
2. 解释器副 agent（webagent.py 调 DeepSeek 网页版，零 API 费用）
   看不见原词，可自由发挥人格化，但占位符必须原样保留
3. 渲染前代码层回填 {{N}} → 原文

关键点：约束靠机制不靠提示词——解释器根本没有原词，
"零篡改"由回填步骤天然保证。调用失败时降级为原文直出（不中断游戏）。

Phase 2.1：文风可切换（style.py）；角色档案（characters.py）——
角色词用 {{Cn}} 独立命名空间（跨轮稳定，同一角色永远同一符文），
角色表注入 system prompt，改写成功后记账出场；{{Cn}} 缺失视为
剧情崩坏直接降级（普通符文保持 Phase 2 行为）。
"""

import json
import re
import subprocess
import sys
from typing import TYPE_CHECKING

from .style import get_style

if TYPE_CHECKING:
    from .characters import Cast
    from .style import Style

# 解释器副 agent（全局工具链，见 ~/.claude/CLAUDE.md）
WEBAGENT = "C:/Users/qwe13/.claude/toolkit/webagent.py"
WEB_TIMEOUT = 180  # 秒；DeepSeek 网页版响应慢，给足余量（120s 实测不够，2026-08-08 调大）

# 关键名词 = 技术名词/路径/命令。特征：中文语境内出现的 ASCII 连续串
#（SQLite、todo.py、D:/github/just_for_fun、sys.argv 等）。
# 过滤纯数字串（编号、次数不保护）；版本号（含点无字母）长度够仍保护。
_IDENT_RE = re.compile(r"[A-Za-z0-9_./\\:@~-]{3,}")


def _is_key_term(s: str) -> bool:
    if s.isdigit():
        return False
    return any(c.isalpha() for c in s) or ("." in s and len(s) >= 5)


def mask(text: str, mapping: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """把关键名词替换为 {{N}} 占位符。

    返回 (占位文本, mapping{原词: 占位符})。同一词多次出现复用同一占位符。
    同一载荷的多个文本域应传入同一个 mapping 共享编号空间——
    各自独立调用会撞号（不同词拿到同一 {{N}}，回填时错位）。
    """
    if mapping is None:
        mapping = {}
    counter = len(mapping)  # 已有词数即下一个编号的上界

    def _repl(m: re.Match) -> str:
        nonlocal counter
        term = m.group(0)
        if not _is_key_term(term):
            return term
        if term not in mapping:
            counter += 1
            mapping[term] = f"{{{{{counter}}}}}"
        return mapping[term]

    return _IDENT_RE.sub(_repl, text), mapping


def unmask(text: str, mapping: dict[str, str]) -> str:
    """回填：占位符 → 原文。解释器侧丢失占位符的情况由调用方校验。"""
    for term, placeholder in mapping.items():
        text = text.replace(placeholder, term)
    return text


def extract_key_terms(text: str) -> set[str]:
    """提取文本中的关键名词集合（验收脚本/诊断用）。"""
    return {m.group(0) for m in _IDENT_RE.finditer(text) if _is_key_term(m.group(0))}


_PLACEHOLDER_RE = re.compile(r"\{\{(?:C)?\d+\}\}")


def _leftover_placeholders(text: str) -> list[str]:
    """残留占位符（解释器自造的 {{N}}/{{Cn}} 或遗漏回填），正常应为空。"""
    return _PLACEHOLDER_RE.findall(text)


def _char_runes(mapping: dict[str, str]) -> set[str]:
    """mapping 中的角色符文集合（{{Cn}}，角色词的稳定占位符）。"""
    return {ph for ph in mapping.values() if ph.startswith("{{C")}


_TAGS = ("【做法】", "【代价】", "【回滚】")


def _valid_payload(data, n_options: int) -> bool:
    """解释器输出的结构校验：字段齐全、选项数一致、三要素完整。"""
    if not isinstance(data, dict) or not isinstance(data.get("question"), str):
        return False
    opts = data.get("options")
    if not isinstance(opts, list) or len(opts) != n_options:
        return False
    for opt in opts:
        if not isinstance(opt, dict):
            return False
        if not isinstance(opt.get("label"), str) or not isinstance(opt.get("detail"), str):
            return False
        if any(tag not in opt["detail"] for tag in _TAGS):
            return False  # 三要素不齐 → 直接降级，不能让格式守门员告警
    return True


def _parse_interpreter(raw: str) -> dict | None:
    """解析 webagent --json 输出里的 {content} → 载荷 dict。

    content 可能带 markdown 代码块，剥掉再 json.loads。
    """
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
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _call_interpreter(payload_json: str, system_prompt: str) -> str | None:
    """同步调 webagent.py（DeepSeek 网页版），返回其 --json stdout。

    失败（网络/凭证/超时/非零退出）返回 None，由调用方降级。
    system_prompt 由文风（style.py）提供。失败原因打印到终端
    （2026-08-08 增加可观测性：此前只打 fallback_hint，无法诊断）。
    """
    cmd = [sys.executable, WEBAGENT, "ds", payload_json, "--system", system_prompt, "--json"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=WEB_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(f"⚠ 叙述者超过 {WEB_TIMEOUT}s 没回应（网络慢或 DeepSeek 排队），本次以原文呈现。", flush=True)
        return None
    except OSError as exc:
        print(f"⚠ 叙述者召唤失败（{type(exc).__name__}），本次以原文呈现。", flush=True)
        return None
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-1][:80] if proc.stderr.strip() else "无诊断输出"
        print(f"⚠ 叙述者退出码 {proc.returncode}（{tail}），本次以原文呈现。", flush=True)
        return None
    return proc.stdout


def novelize_payload(
    payload: dict,
    style: "Style | None" = None,
    cast: "Cast | None" = None,
) -> dict:
    """主入口：把 {question, options} 载荷按文风改写（玩家侧用）。

    流程：mask（普通词 {{N}} + 角色词 {{Cn}} 双命名空间）→ 解释器改写
    → 回填 → 结构校验。任何一步失败都降级返回原文（结构不变），
    并打一行提示——改写是调味品，不能阻塞游戏主流程。

    Phase 2.1 扩展：style 切换文风；cast 提供已立档角色的稳定占位符
    （跨轮次同一角色同一 {{Cn}}）与角色表（注入 system prompt），
    改写成功后记账出场。两个参数缺省 = Phase 2 精确行为。
    """
    style = style or get_style()
    if cast is not None:
        # 重置本轮 transient（降级时不残留上一轮出场名单）
        cast.scene_names = []
        cast.scene_raw_text = ""
        cast.scene_rune_to_term = {}
    # 1. 提取所有文本域并占位；角色词先播种进共享 mapping（跨轮稳定），
    #    普通词由 mask 从 len(mapping) 起编号，天然避开 {{Cn}} 命名空间
    masked = {
        "question": payload["question"],
        "options": [
            {"label": opt.get("label", ""), "detail": opt.get("detail", "")}
            for opt in payload["options"]
        ],
    }
    mapping: dict[str, str] = {}
    if cast is not None:
        for text in [payload["question"]] + [
            o.get("label", "") + " " + o.get("detail", "") for o in payload["options"]
        ]:
            for m in _IDENT_RE.finditer(text):
                term = m.group(0)
                if term not in mapping and _is_key_term(term):
                    ph = cast.placeholder_for(term)
                    if ph:
                        mapping[term] = ph
    masked["question"], _ = mask(masked["question"], mapping)
    for opt in masked["options"]:
        for key in ("label", "detail"):
            opt[key], _ = mask(opt[key], mapping)

    # 2. 调解释器（system prompt 由文风提供；{roster} 槽位注入角色表，
    #    空档案时替换为空串）
    system = style.system_template.replace(
        "{roster}", cast.roster_text() if cast else ""
    )
    raw = _call_interpreter(json.dumps(masked, ensure_ascii=False), system)
    if raw is None:
        print(style.fallback_hint, flush=True)
        return payload
    data = _parse_interpreter(raw)
    if data is None:
        print("⚠ 叙述者的回答不是可解析的 JSON，本次以原文呈现。", flush=True)
        return payload
    if not _valid_payload(data, len(payload["options"])):
        print("⚠ 叙述者的回答缺字段或选项缺【做法】【代价】【回滚】三要素，本次以原文呈现。", flush=True)
        return payload

    # 3. 角色符文缺失检测：发出的 {{Cn}} 必须全部出现在输出里——角色是
    #    剧情核心，被省略 = 该角色从剧本消失，直接降级（普通符文保持
    #    Phase 2 行为，仅靠提示词约束）。记账也在回填前（需用符文定位台词）。
    sent_runes = _char_runes(mapping)
    out_text = json.dumps(data, ensure_ascii=False)
    if sent_runes:
        missing = sorted(r for r in sent_runes if r not in out_text)
        if missing:
            print(f"⚠ 角色 {missing} 从剧本中消失了，本次以原文呈现。", flush=True)
            return payload
    if cast is not None:
        cast.note_appearance(sent_runes, out_text)
        cast.scene_raw_text = out_text
        cast.scene_rune_to_term = {ph: term for term, ph in mapping.items()}

    # 4. 回填
    data["question"] = unmask(data["question"], mapping)
    for opt in data["options"]:
        opt["label"] = unmask(opt["label"], mapping)
        opt["detail"] = unmask(opt["detail"], mapping)

    # 5. 残留占位符兜底校验：正常应为空（说明解释器丢了符文）
    leftovers = _leftover_placeholders(json.dumps(data, ensure_ascii=False))
    if leftovers:
        print(f"⚠ 叙述者弄丢了符文 {leftovers}，本次以原文呈现。", flush=True)
        return payload
    return data
