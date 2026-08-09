"""角色档案（Phase 2.1）：技术名词人格化/持久化的数据层。

设计要点：
- 词占位符 {{Ck}} 独立命名空间（与普通 {{N}} 结构不相交），**每词一个
  唯一占位符、编号跨轮持久** —— 同一角色的不同变体（SQLite/sqlite3）
  各自独立符文，回填互不干扰；roster 按角色分组列出其全部符文，
  解释器据此维持同一形象。
  （2026-08-08 实测修复：原设计"一角色一符文 {{Cn}}"导致同角色多词
  共享占位符，unmask 顺序替换后全部回填成首词——真实会话中所有技术
  名词被替换成 CLI。）
- 记账与创意分离：meetings/last_line 宿主在改写成功时记账
  （note_appearance，不依赖编剧成败）；name/persona/affinity 由编剧
  提案（editor.py）、宿主钳制合并（update_from_editor）。
- 合并 = union，但 aliases 收紧：只有与主词 merge_key 相同的变体才
  并入（编剧过度合并的异类词不污染角色）；load 时清洗历史非法别名。
- 所有 IO 降级链：档案损坏/缺失/写失败都不抛异常，打一行提示继续。
"""

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

# 立档钳制（2026-08-09 live 实测）：编剧把整章 9 个路径/文件词全部
# 独立立档 → 后续每章载荷 10+ 个 {{C}} 角色符文 + 普通符文，解释器
# 压力过大开始丢/自造普通符文（第 3 章起连续降级）。宿主按数量钳制
# 超出的提案丢弃（fail-soft，与编剧契约校验同一哲学）。
MAX_CHARACTERS = 8          # 周目级角色总量上限
MAX_NEW_CHARS_PER_ROUND = 3  # 单幕新立档上限

SAVE_PATH = Path(__file__).parent / "save" / "cast.json"

_CHAR_RUNE_RE = re.compile(r"^\{\{C(\d+)\}\}$")
# 无锚点扫描版（note_appearance 从改写文本里找 {{Ck}}；锚点版只适配单个符文）
_ANY_RUNE_RE = re.compile(r"\{\{C\d+\}\}")
# 普通符文（{{数字}}）是每轮重建的局部编号，跨轮持久化会错位——last_line
# 记账时剥离；{{Ck}} 跨轮稳定命名空间，保留（roster 隔离纪律见下）
_PLAIN_RUNE_RE = re.compile(r"\{\{\d+\}\}")


def merge_key(term: str) -> str:
    """合并键：去尾部数字 + 大小写折叠。

    "SQLite"/"sqlite3"/"sqlite" 的 merge_key 都是 "sqlite"，归并为
    同一角色。_is_key_term 已过滤纯数字串，此处不会退化为空串。
    """
    return re.sub(r"\d+$", "", term).casefold()


@dataclass
class Character:
    """一个立档角色。id 是主词，aliases 是同实体变体（同 merge_key）。"""

    n: int            # 角色编号
    id: str           # 主词（原词，如 "sqlite3"）
    name: str         # 形象名（如 "小石"）
    persona: str      # 中性人设（不含文风化台词，切文风不塌）
    affinity: int     # 好感度 0-100，初始 50
    meetings: int     # 出场次数
    last_line: str    # 最近一句台词/互动摘要（≤40 字）
    absent_rounds: int = 0  # 连续缺席幕数（点卯依据；出场清零，每幕 +1）
    aliases: list[str] = field(default_factory=list)


@dataclass
class Cast:
    """角色档案：角色（创意层）+ 词占位符表（机制层）。

    characters: n → Character；term_placeholders: 原词 → {{Ck}}（每词
    唯一、跨轮持久）；next_t 是词占位符计数器。scene_* 是每轮 transient
    （供渲染前打印与编剧调用）。
    """

    characters: dict[int, Character] = field(default_factory=dict)
    next_n: int = 1
    next_t: int = 1
    term_placeholders: dict[str, str] = field(default_factory=dict)
    scene_names: list[str] = field(default_factory=list)  # 本轮出场角色名（transient）
    scene_raw_text: str = ""                              # 本场改写文本（回填前，供编剧）
    scene_rune_to_term: dict[str, str] = field(default_factory=dict)  # 本轮符文→原词（供编剧）
    _ph_to_n: dict[str, int] = field(default_factory=dict, repr=False)  # 占位符→角色 n（内存态）

    # ---------- 占位符 ----------

    def _find_by_key(self, term: str) -> Character | None:
        """按 merge_key 找既有角色（id 与 aliases 都查）。"""
        key = merge_key(term)
        for ch in self.characters.values():
            keys = [merge_key(ch.id)] + [merge_key(a) for a in ch.aliases]
            if key in keys:
                return ch
        return None

    def placeholder_for(self, term: str) -> str | None:
        """term 命中既有角色 → 该词的持久占位符 {{Ck}}（每词唯一，跨轮稳定）。

        同一角色的不同变体各自独立符文（回填互不干扰），roster 分组
        展示让解释器知道它们是同一人。未立档返回 None（走普通符文）。
        """
        ch = self._find_by_key(term)
        if ch is None:
            return None
        ph = self.term_placeholders.get(term)
        if ph is None:
            while f"{{{{C{self.next_t}}}}}" in self._ph_to_n:
                self.next_t += 1  # 避让既有占位符（含旧式角色符文 {{Cn}}）
            ph = f"{{{{C{self.next_t}}}}}"
            self.next_t += 1
            self.term_placeholders[term] = ph
            self._ph_to_n[ph] = ch.n
        return ph

    # ---------- 档案文本（注入解释器 system prompt） ----------

    def roster_text(self) -> str:
        """角色表：占位符（按角色分组）→ 形象名/人设/好感/上次台词。

        纪律约束：严格不含原词——解释器看不到原词是 nonce 方案的
        设计初衷（泄漏不破坏回填机制，但破坏体验，此处守住）。
        """
        if not self.characters:
            return ""
        by_n: dict[int, list[str]] = {}
        for term, ph in self.term_placeholders.items():
            n = self._ph_to_n.get(ph)
            if n is not None:
                by_n.setdefault(n, []).append(ph)
        lines = ["【角色表】"]
        for ch in sorted(self.characters.values(), key=lambda c: c.n):
            phs = sorted(by_n.get(ch.n, []), key=lambda p: int(_CHAR_RUNE_RE.match(p).group(1)))
            runes = "、".join(phs) if phs else f"{{{{C{ch.n}}}}}"
            tail = f"；好感 {ch.affinity}"
            if ch.last_line:
                tail += f"；上次她说：\"{ch.last_line}\""
            lines.append(f"- {runes}——{ch.name}：{ch.persona}{tail}")
        return "\n".join(lines)

    # ---------- 宿主记账（不依赖编剧成败） ----------

    def tick_absent(self) -> None:
        """每幕开头调用：全体角色连续缺席幕数 +1（出场时 note_appearance 清零）。

        点卯依据（2026-08-09）：立档词与后续幕载荷往往无重叠（五章话题
        独立），宿主据此选"最久未出场"角色注入【本场必现】段。
        """
        for ch in self.characters.values():
            ch.absent_rounds += 1

    def pick_due_char(self) -> tuple[str, str, int] | None:
        """选"连续缺席 ≥2 幕"中缺席最久的角色 → (主符文, 形象名, 缺席幕数)。

        None = 没有该出场还没出场的角色（不注入必现段）。
        """
        due = [c for c in self.characters.values() if c.absent_rounds >= 2]
        if not due:
            return None
        ch = max(due, key=lambda c: c.absent_rounds)
        return f"{{{{C{ch.n}}}}}", ch.name, ch.absent_rounds

    def note_appearance(self, rune_set: set[str], scene_text: str) -> None:
        """改写成功后记账：出场次数去重 +1、记 last_line、填本轮出场名单。

        scene_text 是回填前的改写文本（含 {{Ck}}，据此定位台词）。

        记账集合 = 发出的符文 ∪ 文本中实际出现的已知 {{Ck}} ∪ 形象名直写
        （2026-08-09 两处实测补丁：① 点卯——本幕载荷无角色词时解释器可凭
        roster 让角色冒头，符文不在发出集合但角色出场了；② 形象名直写——
        解释器看 roster 拿到形象名（小石）后直接写名字而非 {{C1}} 符文，
        玩家侧体验一致但符文扫描不到，按 name 也记账）。
        出场角色 absent_rounds 清零（缺席计数随记账复位）。
        """
        names = []
        seen = set(_ANY_RUNE_RE.findall(scene_text))
        runes = sorted(
            (r for r in (set(rune_set) | seen) if _CHAR_RUNE_RE.match(r)),
            key=lambda r: int(_CHAR_RUNE_RE.match(r).group(1)),
        )
        for rune in runes:
            n = self._ph_to_n.get(rune)
            if n is None:
                continue
            ch = self.characters.get(n)
            if ch is None:
                continue
            ch.meetings += 1
            ch.absent_rounds = 0
            idx = scene_text.find(rune)
            if idx != -1:
                # 取符文后的台词片段：去符文本身与 JSON 转义引号
                seg = (
                    scene_text[idx:idx + 80]
                    .replace(rune, "", 1)
                    .replace("\\n", " ")
                    .replace('\\"', '"')
                    .strip()
                )
                ch.last_line = _PLAIN_RUNE_RE.sub("", seg)[:40]
            names.append(ch.name)
        # 形象名直写：解释器直接用 name 而非符文（按 name 定位台词）
        for ch in self.characters.values():
            if ch.n in {self._ph_to_n.get(r) for r in runes}:
                continue  # 该角色已按符文记账
            if ch.name and ch.name in scene_text:
                ch.meetings += 1
                ch.absent_rounds = 0
                idx = scene_text.find(ch.name)
                seg = (
                    scene_text[idx:idx + 80]
                    .replace(ch.name, "", 1)
                    .replace("\\n", " ")
                    .replace('\\"', '"')
                    .strip()
                )
                ch.last_line = _PLAIN_RUNE_RE.sub("", seg)[:40]
                names.append(ch.name)
        self.scene_names = names

    # ---------- 编剧合并（union，aliases 收紧） ----------

    def update_from_editor(self, records: list[dict], rune_to_term: dict[str, str]) -> list[str]:
        """合并编剧输出（editor.py 已做白名单校验）。

        按 rune → 原词 → merge_key 归并：命中既有角色 → 覆盖
        persona/affinity；aliases 只并入与主词同 merge_key 的变体
        （编剧过度合并的异类词不污染角色）。未命中 → 立档
        （n=next_n++，id 预置占位符 {{Cn}} 保持跨轮稳定）。
        返回新立档角色的 id 列表。

        立档钳制（2026-08-09 live 实测）：编剧把整章 9 个路径/文件词
        全部独立立档 → 后续每章载荷 10+ 个 {{C}} 角色符文 + 普通符文，
        解释器压力过大开始丢/自造普通符文（第 3 章起连续降级）。宿主
        侧按数量钳制：单幕新增 ≤MAX_NEW_CHARS_PER_ROUND、总量
        ≤MAX_CHARACTERS，超出的提案丢弃（fail-soft，与契约校验同哲学）。
        """
        new_ids = []
        for rec in records:
            runes = [r for r in rec.get("runes", []) if r in rune_to_term]
            if not runes:
                continue  # 未知符文已过滤，过滤后为空则整条丢弃
            name = str(rec.get("name", "")).strip()[:20]
            if not name:
                continue
            terms = [rune_to_term[r] for r in runes]
            ch = None
            for t in terms:
                ch = self._find_by_key(t)
                if ch is not None:
                    break
            if ch is None:
                if (
                    len(self.characters) >= MAX_CHARACTERS
                    or len(new_ids) >= MAX_NEW_CHARS_PER_ROUND
                ):
                    continue  # 立档上限钳制：超限提案丢弃
                ch = Character(
                    n=self.next_n, id=terms[0], name=name,
                    persona="", affinity=50, meetings=0, last_line="",
                )
                self.next_n += 1
                self.characters[ch.n] = ch
                # 主词预置占位符 {{Cn}}（跨轮稳定：下轮起同一符文）
                ph = f"{{{{C{ch.n}}}}}"
                self.term_placeholders.setdefault(ch.id, ph)
                self._ph_to_n[ph] = ch.n
                new_ids.append(terms[0])
            # aliases 收紧：仅同 merge_key 的变体并入
            base_key = merge_key(ch.id)
            for t in terms:
                if t != ch.id and merge_key(t) == base_key and t not in ch.aliases:
                    ch.aliases.append(t)
            persona = str(rec.get("persona", "")).strip().replace("\n", " ")[:300]
            if persona:
                ch.persona = persona
            aff = rec.get("affinity")
            if isinstance(aff, int) and not isinstance(aff, bool):
                ch.affinity = max(0, min(100, aff))
        return new_ids

    # ---------- 持久化（全部 fail-soft） ----------

    def save(self) -> None:
        """原子写：临时文件 + os.replace，防 Ctrl+C 半写 JSON。"""
        data = {
            "next_n": self.next_n,
            "next_t": self.next_t,
            "term_placeholders": dict(self.term_placeholders),
            "characters": [asdict(ch) for ch in self.characters.values()],
        }
        try:
            SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = SAVE_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, SAVE_PATH)
        except OSError:
            print("⚠ 角色档案保存失败（本次出场记录未落盘）。", flush=True)

    @classmethod
    def load(cls) -> "Cast":
        """读档；缺失/损坏/结构非法 → 空档 + 提示行，不抛异常。

        兼容旧档（无 term_placeholders 字段）：角色 id 预置旧式占位符
        {{Cn}}（跨轮稳定不中断）；非法 aliases（merge_key 与主词不同，
        历史上被编剧过度合并的异类词）清洗剔除。
        """
        if not SAVE_PATH.exists():
            return cls()
        try:
            data = json.loads(SAVE_PATH.read_text(encoding="utf-8"))
            chars: dict[int, Character] = {}
            for rec in data.get("characters", []):
                n = rec.get("n")
                if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n in chars:
                    continue  # 坏条丢弃（n 冲突也丢弃）
                chars[n] = Character(
                    n=n,
                    id=str(rec.get("id", "")),
                    name=str(rec.get("name", "")),
                    persona=str(rec.get("persona", "")),
                    affinity=50 if not isinstance(rec.get("affinity"), int) or isinstance(rec.get("affinity"), bool)
                            else max(0, min(100, rec["affinity"])),
                    meetings=rec.get("meetings", 0) if isinstance(rec.get("meetings"), int) else 0,
                    last_line=str(rec.get("last_line", "")),
                    aliases=[str(a) for a in rec.get("aliases", []) if isinstance(a, str)],
                )
            next_n = data.get("next_n", 1)
            if not isinstance(next_n, int) or next_n <= max(chars, default=0):
                next_n = max(chars, default=0) + 1
            terms = {
                str(k): str(v) for k, v in data.get("term_placeholders", {}).items()
            }
            # 占位符 → 角色（内存态）重建
            ph_to_n: dict[str, int] = {}
            for term, ph in terms.items():
                for ch in chars.values():
                    if merge_key(term) in (merge_key(ch.id), *(merge_key(a) for a in ch.aliases)):
                        ph_to_n[ph] = ch.n
                        break
            # 旧档兼容：角色 id 预置占位符 {{Cn}}，跨轮稳定不中断
            for n, ch in chars.items():
                if ch.id not in terms:
                    terms[ch.id] = f"{{{{C{n}}}}}"
                    ph_to_n[f"{{{{C{n}}}}}"] = n
            # 清洗非法 aliases（merge_key 与主词不同 = 历史过度合并）
            dropped = []
            for ch in chars.values():
                keep = [a for a in ch.aliases if merge_key(a) == merge_key(ch.id)]
                if len(keep) != len(ch.aliases):
                    dropped.extend(a for a in ch.aliases if a not in keep)
                    ch.aliases = keep
            if dropped:
                print(f"⚠ 角色档案清洗：移除 {len(dropped)} 个非法别名 {dropped[:5]}…（编剧过度合并的异类词）", flush=True)
            # next_t 避让：大于所有既有占位符编号与角色编号
            used = {int(m.group(1)) for m in map(_CHAR_RUNE_RE.match, terms.values()) if m}
            next_t = max(used | set(chars), default=0) + 1
            return cls(characters=chars, next_n=next_n, next_t=next_t,
                       term_placeholders=terms, _ph_to_n=ph_to_n)
        except (OSError, json.JSONDecodeError, ValueError):
            print("⚠ 角色档案损坏，已重置为空档。", flush=True)
            return cls()

    @classmethod
    def reset(cls) -> None:
        """删档（cli --reset-cast）：新周目/换角色。"""
        try:
            SAVE_PATH.unlink(missing_ok=True)
        except OSError:
            pass
