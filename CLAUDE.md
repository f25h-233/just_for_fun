# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

just_for_fun —— 兴趣项目集合，每个项目一个文件夹。当前仓库主体是 **galgame-coding**：给 Claude Code 包上 galgame（视觉小说）的壳，玩法循环为 **抉择 → 轻小说化 → 回档**。

- **Phase 0（已完成）**：验证了 SDK 宿主模式下的交互拦截/注入。验证脚本在仓库根目录（`phase0_*.py`）+ `scratch/`。
- **Phase 1（已完成，2026-08-08）**：文本版前端，替换掉硬编码假抉择（`pick = 1`）。代码在 `galgame_coding/` 包（**注意是下划线**：`python -m galgame-coding.cli` 不可行，连字符不是合法模块名）。
- **Phase 2（已完成，2026-08-08）**：轻小说化。ask_player 载荷在渲染前经 `novel.py` 改写为日轻文本（nonce 占位符方案 + DeepSeek 网页版解释器），agent 侧仍见原文。验收 20/20（round-trip 10/10 + live 零篡改 10/10），真实会话跑通。
- **Phase 2.1（已完成，2026-08-08）**：文风模块化（`style.py`：日轻 + 武侠可切换）+ 角色档案（`characters.py`：技术名词人格化/持久化，`{{C<n>}}` 独立命名空间跨轮稳定 + `editor.py` 编剧副 agent 每轮更新档案）。离线验收 6/6。
- **Phase 3（已完成，2026-08-08）**：回档。玩家在抉择输入 `r` → 回档子菜单选目标轮次 → **切断当前会话 + 重建任务描述（已确定剧情摘要 + 回档指令）重启新会话**（SDK 会话内无法回退，回档 = 新会话）。核心：`history.py`（抉择历史 + 截断语义）、`prompt.py` 回档段追加在任务之后、`galgame.py` 外层回档循环。离线验收 10/10（`phase3_accept_rollback.py`）。
- **Phase 3.2（补全阶段完成 2026-08-09）**：主线贯穿 + 角色出场 + "神似"对应（四路调研定稿）。核心：`story.py` 剧情记忆（宿主侧双层记忆：上一幕全文 + 每幕摘要滚动窗口）+ 解释器提示词 v2（剧本纪律共享段 `_STORY_RULES`：幕四拍/主角在场/角色纪律/幕间链接/对应法则/写回契约）+ 写回契约（解释器同次调用输出 `summary_delta`/`importance`，宿主记账，零新增调用）。**缺陷诊断（实测证据）**：cast.json 11 词立档 4 形象但 meetings 几乎全 0（角色被立档但从不进正文）；改写只是逐条文学化复述选项（无主线、选项像方案列表）。**补全阶段（2026-08-09）**：回档联动（story.truncate 接入 tools.py + 轮号对齐机制，见结论 17）+ 离线验收 `phase32_accept_story.py` 9/9（含降级轮对齐核心回归）。
**live 复测（2026-08-09 完成）**：五章真实会话 6 轮，修复 8 个真 bug（空 cast 条件化 `CHAR_RULES` 禁自造符文 / MAX_TURNS 60→90 / 立档钳制 `MAX_CHARACTERS=8`+`MAX_NEW_CHARS_PER_ROUND=3` / 自造编号禁令 / DeepSeek 随机故障双层重试 / 点卯结构性修复三件套（unmask 补 cast 全量回填 + note_appearance 扫 `_ANY_RUNE_RE` + 注入条件放宽）/ 必现注入 `pick_due_char` 缺席 ≥2 幕点名 / 形象名直写记账 name 扫描）+ 最终轮（live32f）验收：`err=False 71 turns $2.70`、抉择 5/5、cast meetings>0 好感跨轮累积（小石 3/55、沃克桑 2/52、刻若 1/50）、必现点卯实证（刻若缺席 3 幕 ch5 登场）、零结构性降级（1 次 ch2 模型服从性 flake：解释器把 {{1}}="tasks" 意译掉，重试仅覆盖解析失败、不覆盖残留符文——留待改进）；**bug 9 修复（验收后）**：last_line 记账剥离本轮局部普通符文 `{{数字}}`（跨轮错位隐患；`{{Ck}}` 跨轮稳定保留），回归 T8 进 phase21 8/8。webagent 可用性：国内令牌 + 无代理直连；**2026-08-10 起默认渠道改为 OpenCode Go 订阅 API（`deepseek-v4-flash`，key 在 `~/.webagent_cred.json` 的 `ds_api_key`）**——DeepSeek 网页版账号触发风控被封，网页版降为兜底渠道。
- TardigradeMail（时光信）已迁出到 `../future_mail/`，此仓库不再涉及。

工作语言为中文（zh-CN）：README、docstring、注释、prompt 均为中文。

## 关键技术结论（Phase 0 验证结果）

这两条是花了真金白银验证出来的架构结论，新代码不要偏离：

1. **AskUserQuestion 在 SDK 宿主模式下不可见**（测试于 Claude Code 2.1.224），无法通过事件流拦截 → 该路线已放弃。注意其坑：旧版本约 37ms 内自动解析空答案（issue #50728），v2.1.200+ 无人响应时会挂起等待。
2. **自定义 MCP 工具 `ask_player` 是既定架构**：通过 `create_sdk_mcp_server` 注册工具（schema 为 `question` + `options`，最多 4 个选项），agent 必须先调用它获取玩家抉择再行动 —— 这就是未来 galgame 前端的交互入口。
3. **前端必须是"对象实例"，不是裸函数**（Phase 1 实测）：`Frontend` Protocol 定义方法形态 `ask(self, ...)`，`make_ask_player` 内部调用 `frontend.ask(...)`；直接传模块级函数会炸 `'function' object has no attribute 'ask'`。Phase 1 实现为 `frontends/terminal.py` 的 `TerminalFrontend` 类。
4. **嵌套 schema `list[dict]` 实测可行**（Phase 1）：选项结构化为 `label` + `detail`（detail 必须含【做法】【代价】【回滚】三要素），无需回退 list[str] + 模板解析。
5. **nonce 占位符方案防篡改（Phase 2 实测）**：关键名词（ASCII 标识符串）→ `{{N}}` → 解释器看不见原词自由改写 → 渲染前代码层回填。机制保证"出现即原样"，零篡改不靠提示词。两个坑：同一载荷多个文本域必须共享 mapping 编号空间（各自独立会撞号）；nonce 防篡改不防省略——解释器可能删掉 `{{N}}` 所在从句，须在解释器提示里强制"每个符文至少出现一次"（实测后缺失归零）。
6. **解释器降级链路**：webagent.py（DeepSeek 网页版）调用失败/输出校验失败/三要素不齐/残留占位符 → 本次直接原文直出（打一行 📖 提示，不阻塞游戏）；另有 `--novel-lite` 提示词凑合版（`LITE_NOVEL_RULES`），约束力弱但零成本。
7. **角色占位符 `{{C<n>}}` 独立命名空间 + 每词唯一（Phase 2.1 实测，含 bug 修复）**：角色词（已立档的技术名词）用前缀命名空间，与普通 `{{数字}}` 结构上不相交——撞号在类型层面不可能发生（曾考虑 `{{100+}}` 号段，普通词超 99 个即撞，"约定"不是"结构"）。**2026-08-08 实测 bug：原"一角色一符文"导致同角色多词（或编剧过度合并的异类词）共享占位符，unmask 顺序替换后全部回填成首词——真实会话中 json/sqlite3/SQL 等全变 CLI**。修复：**每词一个唯一占位符**（cast.json 的 `term_placeholders` 映射 + `next_t` 计数器，跨轮持久），同一角色的变体各自独立符文、roster 按角色分组同列（解释器仍视为同一人）。三道防线：每词独立符文（结构免疫）+ load 清洗非法 aliases（merge_key ≠ 主词的剔除）+ 编剧提示词收紧（合并仅限同实体拼写、命令词/参数/路径不立档、单条 runes ≤3）。回归用例见 phase21_accept_cast.py T7。
8. **编剧副 agent（Phase 2.1）**：每次抉择解释器改写后另调一次 webagent（+4-22s），输入 = 旧角色表 + 回填前改写文本 + 符文对照表；输出 JSON 数组 `[{runes, name, persona, affinity}]`——**只给创意，id 由宿主从 rune 解析**（runes 是宿主 mapping 闭集白名单，编剧不编 id）。校验 fail-soft（编剧输出不进渲染路径，失败只损失人设更新）。**记账/创意分离**：meetings/last_line 宿主在改写成功时记账（不依赖编剧成败），name/persona/affinity 编剧提案宿主钳制。
9. **编剧调用时机（Phase 2.1 设计定稿）**：推迟到 `frontend.ask()` 返回之后（玩家阅读时间天然隐藏延迟，两条降级链不叠加在关键路径上）。`{{Cn}}` 缺失 = 角色从剧本消失 → 直接降级原文（普通符文保持 Phase 2 的提示词约束，不降级）。`--novel-lite` 时 cast 只读（掩码/回填照常，禁编剧与保存）。
10. **merge_key（Phase 2.1）**：`去尾数字 + casefold`（SQLite/sqlite3/sqlite → 同一角色）；纯 casefold 对带数字变体不成立。persona 存中性本质（不存文风化台词）→ 切文风只换表皮、性格不塌。
11. **回档 = 会话切断重启（Phase 3）**：SDK 会话内无法回退，回档必须 = 切断当前会话 + 用重建的任务描述开新会话。新会话任务 = 原任务 + 前 N-1 轮已确定抉择摘要（**追加在任务之后**，最后注入优先级最高——否则 tasks.py 里"动手前必须先调用 ask_player"会让回档后的 agent 重问已确定轮次）+ 回档指令（**独立注入**：回档到第 1 轮时 established 为空，但指令不能丢）。
12. **History 截断语义（Phase 3）**：回档到第 N 轮 = 第 N..end 轮记录作废（truncate 到 N-1，截断而非"保留+过滤"——索引不重复、describe 无需参数、语义自洽）。每条记录**双存**：原文（agent 侧，prompt 重建用）+ 改写版（玩家侧，回档菜单展示用——玩家刚读过的就是改写版）。History 不持久化（会话内状态，Ctrl+C 即丢失；cast.json 是周目级资产才有 finally 兜底）。回档不改 cast（角色记得之前的分支）。回档不跑编剧（旧分支角色更新不进新档案）。
13. **剧情记忆双层结构（Phase 3.2，四路调研定稿）**：解释器是无状态调用，记忆必须宿主侧维护、调用时注入——`story.py` 的 StoryMemory（会话级，与 History 同级）：**短时 = 上一幕改写全文**（prev_scene，直接接续，注入在最接近载荷处）+ **长时 = 每幕 1-3 句摘要**（summaries 滚动窗口：首条全局锚点 + 最近 6 条，防记忆膨胀——只增不删会让注入段噪声越来越大）。**nonce 隔离纪律：prev_scene/summaries 存符文形态**（{{N}}，含 {{C}}）——前情要注入给解释器，泄漏原词破坏"解释器只见符文"的核心隔离。玩家选择是宿主在 ask 后才知道的，用 prepare_scene（改写成功时准备）/record_scene（玩家选择后提交）两段式补上。
14. **注入顺序固定（Phase 3.2）**：system prompt 组装 = 文风模板（含 roster）→ 剧本纪律 `_STORY_RULES`（所有文风共享的拼接段）→ 前情梗概 → 上一幕结尾。实证"最后注入优先级最高"——接续锚点要离载荷最近。剧本纪律内容（四路调研综合）：幕四拍（开·承接/承·角色对话展开/转·选项动作化/结·即时后果+幕尾钩）、主角在场（"我"每幕 ≥1 句行动或心声，选项禁方案列表）、角色纪律（每幕 ≥1 立档角色实质对话；连续 2 幕未出场要"点卯"；好感度档位定语气）、幕间链接（上幕结果是本幕既定前提；幕尾钩指向章级/总目标）、对应法则（【做法】→一个场景事件一映射一、【代价】→威胁程度与原文一致禁夸大失败为成功、【回滚】→退路；回顾式时态；双关行可选）、写回契约（summary_delta ≤120 字 + importance 0-3 随 JSON 一并输出）。
15. **降级轮零记账（Phase 3.2 修复，含 Phase 2 遗留 bug）**：novelize 的记账（cast 出场/summary/上一幕素材）必须发生在**所有降级检查通过之后**——降级轮玩家看到的是原文，剧情/角色记忆不能引用一场没演出的"剧情"。顺序：回填前快照（符文形态）→ 角色符文缺失检测 → 回填 → 残留检查（渲染路径 question/options）→ 全过才记账。**Phase 2 遗留同款 bug**：cast 记账原在残留检查前，降级轮会记出场（已一并修复）。残留检查范围收紧：写回字段（summary_delta/importance）不进渲染路径，解释器在摘要里保留符文是正常行为，不能误判"丢符文"。
16. **FIREBALL 教训（Phase 3.2 调研）**：LLM 改写真实日志的两个典型翻车——夸大结果（日志失败写成成功）与替玩家行动（叙述 agent/玩家做出日志中不存在的动作）。nonce 只防"篡改名词"，防不了这两类"叙述层犯罪"——靠提示词约束（对应法则）防，校验在提示词里而非结构。
17. **回档联动轮号对齐（Phase 3.2 补全，2026-08-09 实测）**：story 的摘要/上一幕只在改写成功轮记账，按"数量"截断会被降级轮错位（作废分支条目残留注入新会话）+ 上一幕陈旧（回档后还是作废分支的最近一幕）+ 当轮 pending 泄漏（回档发生在 ask 期间，未提交素材若不清，新会话降级轮会误提交）。**结构免疫修法**：StoryMemory 自持轮号 `_round_no`，tools 每轮（**含降级轮**）begin_round 占号，条目携带轮号，truncate(keep) **按轮号过滤**（非计数）+ 场景按轮存档（`_scenes`）恢复分支点上一幕 + 清空 pending + 重置轮号使新会话重新对齐。降级轮"无条目但占号"是对齐的关键——与 History 轮号一一对应，回档 = 同一轮号边界双截断。

整体方向：用 `claude_agent_sdk`（Python）以宿主模式嵌入真实 Claude Code CLI，通过事件流 + 自定义工具与 agent 交互。

## 运行

依赖：Python 3.10+，`pip install claude-agent-sdk`，本机装有已认证的 Claude Code CLI（SDK 会拉起它）。无包清单、无构建步骤，脚本直接运行：

```bash
python phase0_intercept.py      # 验证事件流拦截（permission_mode=acceptEdits）
python phase0_custom_tool.py    # 验证 ask_player 自定义工具（bypassPermissions，会写盘！）
python phase0_probe_tools.py    # 探测宿主模式下 agent 实际可用的工具列表
python phase2_accept_novel.py   # Phase 2 验收：round-trip（零网络零费用）
python phase2_accept_novel.py --live   # 加跑真实链路（调 DeepSeek 解释器，10 次调用，慢）
python phase21_accept_cast.py   # Phase 2.1 验收：文风/角色档案（离线 6 项，零费用）
python phase21_accept_cast.py --live    # 加跑真实两轮（解释器+编剧各 2 次，慢）
python phase3_accept_rollback.py  # Phase 3 验收：回档（离线 10 项，零费用）
python phase3_accept_rollback.py --live  # 加跑真实回档（两个真实会话，慢，耗 API 费用）
python phase32_accept_story.py  # Phase 3.2 验收：剧情记忆 + 回档联动（离线 9 项，零费用）
run.bat                         # 一键启动（Windows）：--menu 菜单，选示例任务或自定义
python -m galgame_coding.cli --menu          # 同上（不带 bat）
python -m galgame_coding.cli                 # 直接跑第一个示例任务（待办 CLI 存储方案抉择）
python -m galgame_coding.cli "自定义任务"    # 自定义任务
python -m galgame_coding.cli --novel-lite    # 日轻化降级：不调解释器，提示词要求 agent 自写日轻口吻
python -m galgame_coding.cli --style wuxia   # 武侠文风（解释器口吻切换）
python -m galgame_coding.cli --reset-cast    # 清空角色档案（新周目/换角色）
```

**注意**：抉择改写走 `novel.py`（Phase 2 默认开启）；每次抉择触发**两次** webagent 调用（解释器改写 + 编剧更新角色档案，各数秒；默认走 OpenCode Go 订阅 API `deepseek-v4-flash`，网页版免费兜底——2026-08-10 起因 DeepSeek 网页版账号触发风控切换），任何失败自动降级（原文直出 / 沿用旧档案），不阻塞游戏。

**注意（Phase 3 回档）**：游戏内抉择输入 `r` 进入回档子菜单（至少完成一轮后可用）。**每次回档 = 一次新的真实 Claude Code 会话 = 额外 API 费用**，无次数上限；回档不改角色档案（cast.json 保留，角色记得之前的分支）；History 不持久化，会话级 Ctrl+C 打断即丢失。

**注意**：
- 每次运行都驱动一次真实的 Claude Code agent 会话并**消耗 API 费用**（最终 ResultMessage 里有 `cost=$...`）。
- `phase0_custom_tool.py` 使用 `permission_mode="bypassPermissions"` 且会在磁盘创建文件（如 `scratch/beta.py`），有副作用，谨慎运行。
- 脚本硬编码 `REPO = "D:/github/just_for_fun"` 绝对路径；`ask_player` 里 `pick = 1` 是 Phase 0 的假抉择，Phase 1 必须由真实前端输入替换。
- 需截获完整问答内容时，连接要开 `include_partial_messages=True`（phase0_intercept.py 的注释）。

## 结构速览

- `phase0_intercept.py` — Phase 0 主验证：拦截 AskUserQuestion 事件流、注入 `tool_result` 答案。`describe()` 把 SDK 消息（Assistant/Result/System）压平成单行摘要，是理解 SDK 消息结构的现成范例。
- `phase0_custom_tool.py` — Phase 0b：`create_sdk_mcp_server(name="galgame", ...)` + `@tool` 注册 `ask_player`，返回 MCP 风格 `{"content": [{"type": "text", ...}]}`。`PROMPT` 演示了如何强制 agent 先抉择再行动。
- `phase0_probe_tools.py` — 补充探测，脚本结构最简，可作新脚本模板。
- `scratch/beta.py` — Phase 0 测试的产物（被测试的 agent 创建的），可删。
- `galgame_coding/` — **Phase 1 包**（下划线，可 `python -m`）：
  - `cli.py` — 入口（Windows UTF-8 控制台处理 + KeyboardInterrupt 兜底）
  - `galgame.py` — 宿主核心：装配 server + 消息循环 + `_QuitSignal`（玩家退出/回档信号）+ **外层回档循环**（`run()` 单会话 `run_session()`，回档后重建任务重启）
  - `history.py` — **Phase 3 抉择历史**：ChoiceRecord（双存原文+改写版）+ History（record/truncate 截断/describe 已确定剧情）
  - `story.py` — **Phase 3.2 剧情记忆**：StoryMemory（上一幕全文 prev_scene + 每幕摘要 summaries 滚动窗口，全符文形态）+ 写回契约记账（record_summary）+ 两段式上一幕（prepare_scene/record_scene）+ **轮号对齐**（begin_round 每轮占号、条目带轮号、truncate 按轮号过滤 + 恢复分支点上一幕，tools.py 回档路径联动）
  - `tools.py` — `make_ask_player(frontend, quit_signal, history, rollback_signal, story)` 工厂，schema 为 `label`+`detail` 结构；回档路径截断历史+置信号+不跑编剧；ask 后 story.record_scene 提交上一幕
  - `prompt.py` — 决策化规则（必须问/禁止问/选项三要素）+ 任务组装（默认取 tasks.py 第一个）+ Phase 3 回档段（established/rollback_at 追加在任务之后）
  - `tasks.py` — 示例任务集（待办 CLI / 照片批量重命名 / md 表格转 CSV），`--menu` 可浏览
  - `frontend.py` + `frontends/terminal.py` — `Frontend` Protocol + `TerminalFrontend` 实现（Phase 4 换 pygame 只新增实现）；Phase 3 起 ask 带 history 参数、`RollbackRequest` 异常（输入 r 回档）
  - `novel.py` — **Phase 2 轻小说化核心**：mask/unmask（nonce 占位符）、解释器封装（webagent.py 调 DeepSeek 网页版）、novelize_payload 主入口 + 多级降级；`extract_key_terms` 供验收脚本。Phase 2.1：`{{Cn}}` 角色命名空间播种/回填/缺失降级。Phase 3.2：`_STORY_RULES` 剧本纪律共享段（所有文风通用）+ story 动态注入（前情梗概→上一幕结尾，顺序固定）+ 写回契约记账 + 降级轮零记账（检查全过才记账）
  - `style.py` — **Phase 2.1 文风注册表**：frozen Style dataclass（system_template + fallback_hint），`STYLES`/`get_style`；新增文风 = 加模板 + 注册表一条。Phase 3.2 起模板只管**口吻**（怎么说话）+ 符文/格式硬规则，叙事纪律在 novel.py 的 `_STORY_RULES`（新增文风自动获得完整剧本能力）。roster 插入用 `.replace("{roster}", ...)`（模板满屏 `{{N}}`，勿用 str.format）
  - `characters.py` — **Phase 2.1 角色档案**：Character/Cast（`{{Cn}}` 稳定占位、roster_text 注入解释器、note_appearance 记账、update_from_editor union 合并、原子写 save/load/reset，全 fail-soft）；`merge_key` 去尾数字+casefold；存档 `save/cast.json`（gitignore）
  - `editor.py` — **Phase 2.1 编剧副 agent**：webagent 调用 + 白名单契约校验（runes 闭集/name 1-20/persona 截 300/affinity 钳 0-100），fail-soft
  - `scratch/todo.py` — 演示任务产物（agent 按玩家选择的方案B 重写为 sqlite3 版，可删）
- `phase2_accept_novel.py` — Phase 2 验收：10 条构造载荷 round-trip（零网络）+ `--live` 真实调解释器零篡改验证
- `phase21_accept_cast.py` — Phase 2.1 验收：6 项离线（monkeypatch 解释器/编剧）+ `--live` 真实两轮角色持续出场
- `phase3_accept_rollback.py` — Phase 3 验收：10 项离线（monkeypatch 解释器/编剧/假 SDK 客户端驱动回档循环）+ `--live` 脚本化前端驱动真实回档（注意：tools 的编剧要 patch `TOOLS.call_editor`，不是 `ED._call_editor`——tools 是直接导入名）

## 测试

无测试框架，无 CI。Phase 0 脚本本身就是验证手段：人工运行 + 检查逐条消息摘要与最终 ResultMessage（错误标志、回合数、费用）。
