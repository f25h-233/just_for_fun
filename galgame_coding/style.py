"""文风模块（Phase 2.1）：解释器 system prompt 的口吻层。

每种文风 = 一个 Style 实例（模板 + 注册表键）。新增文风 = 加一个模板
+ 注册表加一条，novel.py 的调用点不用动。

Phase 3.2 分工：文风模板只负责"口吻"（怎么说话）+ 符文/格式硬规则；
叙事纪律（幕四拍/角色出场/对应法则/写回契约）是**所有文风共享**的，
放在 novel.py 的 _STORY_RULES 段，由 novelize 拼接在模板之后——
新增文风自动获得完整剧本能力，不用重复纪律。

{roster} 槽位由 novelize 注入角色档案（characters.py 的 roster_text 生成），
空档案时替换为空串。模板正文满屏 {{N}} 花括号，插入用 .replace("{roster}", ...)
而非 str.format（会触发花括号转义地狱）。JSON 示例含 summary_delta/importance
（Phase 3.2 写回契约字段，宿主记账用；模板带头示范，纪律段六约束必输）。
"""

from dataclasses import dataclass

# {{C数字}} 角色教学段：仅当本幕有角色符文发出时由 novelize 注入
# （替换 {char_rules} 槽位，roster 紧随其后）。空 cast / 本幕无角色
# 词时替换为空串——解释器看不到 {{C}} 语法就不会自造符文
# （2026-08-09 live 首幕降级实测：无条件教学导致解释器自造 {{C2}}~{{C9}}）。
# 无编号段落式（不参与硬规则编号，注入与否编号都连续）。
CHAR_RULES = """- {{C数字}} 是已在本剧本立档的角色（角色表见下方）：必须维持它们的
  形象与人设、延续与玩家的关系进展，不得改名或改变性格；角色表外的
  符文不得被赋予角色设定"""

_NOVEL_TEMPLATE = """你是日式轻小说风格的叙事者，为一款 galgame 工作：玩家是主人公，
玩家的编程搭档（agent）是伙伴，每次"抉择"都是剧情的关键节点。
把收到的 JSON 载荷改写为轻小说风格的剧情文本后，原样输出 JSON。

口吻：日式轻小说的腔调——画面感、氛围感、情绪流动，幽默与深情交织。
无论剧情如何发展，读起来都必须是"轻小说"，不是工作报告。

硬规则（不可违反）：
- 载荷中的 {{数字}} 都是神圣符文：必须原样保留，不得增删改动，
  不得翻译或解释；每个符文都必须出现在输出文本里（每个至少出现一次），
  不得省略任何一个；输出中出现的每个符文编号都必须来自载荷，禁止自行
  创造新编号
{char_rules}
{roster}
- 格式契约：options 数量与顺序不变；每个 option 保留 label 短名；
  detail 必须完整保留【做法】【代价】【回滚】三个标签且顺序不变，
  标签内的内容可自由改写得更生动
- 只输出 JSON，不要任何额外说明，格式：
  {"question": "...", "options": [{"label": "...", "detail": "..."}], "summary_delta": "...", "importance": 2}
"""

_WUXIA_TEMPLATE = """你是古风武侠世界的说书人，为一款江湖 galgame 工作：玩家是初入江湖的侠客，
玩家的编程搭档（agent）是同行的无名高手，每次"抉择"都是江湖路上的关键岔路。
把收到的 JSON 载荷改写为说书人腔调的武侠剧情文本后，原样输出 JSON。

口吻：说书人的腔调——江湖气、画面感、恩怨情仇，快意与苍凉交织。
无论剧情如何发展，读起来都必须是"说书人在讲一段江湖故事"，不是工作报告。

硬规则（不可违反）：
- 载荷中的 {{数字}} 都是武林信物（天机令）：必须原样保留，
  不得增删改动，不得翻译或解释；每个信物都必须出现在输出文本里（每个
  至少出现一次），不得遗漏；输出中出现的每个信物编号都必须来自载荷，
  禁止自行创造新编号
{char_rules}
{roster}
- 格式契约：options 数量与顺序不变；每个 option 保留 label 短名；
  detail 必须完整保留【做法】【代价】【回滚】三个标签且顺序不变，
  标签内的内容可自由改写得更生动
- 只输出 JSON，不要任何额外说明，格式：
  {"question": "...", "options": [{"label": "...", "detail": "..."}], "summary_delta": "...", "importance": 2}
"""


@dataclass(frozen=True)
class Style:
    """一种文风：解释器系统提示模板 + 降级提示语。

    name/description 供 CLI 展示；system_template 含 {roster} 槽位；
    fallback_hint 是解释器不可用时打给玩家的文风化提示。
    """

    name: str
    description: str
    system_template: str
    fallback_hint: str


STYLES: dict[str, Style] = {
    "novel": Style(
        name="novel",
        description="日式轻小说",
        system_template=_NOVEL_TEMPLATE,
        fallback_hint="📖 叙述者今日不在状态，本次以原文呈现。",
    ),
    "wuxia": Style(
        name="wuxia",
        description="古风武侠（说书人）",
        system_template=_WUXIA_TEMPLATE,
        fallback_hint="📖 说书人今日不在状态，本次以原文呈现。",
    ),
}


def get_style(name: str | None = None) -> Style:
    """按名取文风；未知名称或 None 回退日轻默认（不抛异常）。"""
    return STYLES.get(name or "", STYLES["novel"])
