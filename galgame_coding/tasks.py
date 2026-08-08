"""示例任务集：给一键启动（run.bat --menu）用的现成任务。

每个任务都满足决策化规则的示范要求：有真实路线分叉、选项结构清晰、
能完整演示"提问 → 玩家选择 → 按选择执行"的一圈。

Phase 3.1：DEMO_TASKS[0] 换成五章连播大任务（cli 无参数默认跑它、
run.bat 直接启动）——多章节强制多次决策，角色才有机会持续出场。
"""

DEMO_TASKS: list[dict] = [
    {
        "name": "五章连播：个人任务管理 CLI",
        "desc": "五章连续大任务（每章一次抉择，共 5 次决策），产出只写 workspace/",
        "task": """任务：在 galgame_coding/workspace/ 下从零开发一个完整的「个人任务管理 CLI」应用（任务条目含标题、截止日期、优先级、完成状态；支持增删改查、筛选、周报统计）。

这是一个五章连续开发的大任务：**严格按章节顺序推进，每章开始前必须先调用 ask_player 询问该章的路线决策，等玩家选择后再实现该章；实现完一章（可运行、可验证）再做下一章；禁止跳过章节、禁止一次性把五章全做完**。每章实现完顺手跑一遍该章的关键命令自证可用。

【总约束】所有产出的文件只能写在 galgame_coding/workspace/ 目录下（可自建子目录）；workspace/ 以外的任何文件都禁止修改、创建、删除（包括 README、测试、验收记录，全部放进 workspace/）。

章节 1（项目骨架）：决定代码结构。动手前先调用 ask_player，三个选项 label 分别为：「方案A：包结构」「方案B：单文件」「方案C：核心+CLI双层」，detail 写清【做法】【代价】【回滚】。

章节 2（数据存储）：决定任务数据怎么存。动手前先调用 ask_player，三个选项 label 分别为：「方案A：sqlite3」「方案B：JSON文件」「方案C：JSON+git提交历史」，detail 写清【做法】【代价】【回滚】。

章节 3（命令交互）：决定命令行怎么解析。动手前先调用 ask_player，三个选项 label 分别为：「方案A：argparse标准库」「方案B：手写解析」「方案C：引入typer依赖」，detail 写清【做法】【代价】【回滚】。

章节 4（输出形态）：决定 list / 周报的展示方式。动手前先调用 ask_player，三个选项 label 分别为：「方案A：纯文本对齐」「方案B：引入tabulate表格」「方案C：ANSI彩色进度条」，detail 写清【做法】【代价】【回滚】。

章节 5（测试与交付）：决定测试与交付物。动手前先调用 ask_player，三个选项 label 分别为：「方案A：pytest+README」「方案B：unittest+README」「方案C：手写冒烟脚本」，detail 写清【做法】【代价】【回滚】。

全部五章完成后，运行一遍关键命令自测，把自测结果写入 workspace/ 的验收记录文件。""",
    },
    {
        "name": "待办清单 CLI",
        "desc": "在 scratch/ 下实现待办 CLI（add/done/list），存储方案三选一",
        "task": """任务：在 galgame_coding/scratch/ 下实现一个待办清单 CLI（add / done / list 三个命令）。

动手前必须先调用 ask_player 询问存储方案，三个选项的 label 分别为：
「方案A：纯标准库JSON」「方案B：sqlite3存储」「方案C：带截止日期版」，
每个选项的 detail 都必须写清【做法】【代价】【回滚】。

等玩家选择后再开始实现。""",
    },
    {
        "name": "照片批量重命名",
        "desc": "在 scratch/ 下写照片批量重命名工具，命名规则三选一",
        "task": """任务：在 galgame_coding/scratch/ 下实现一个照片批量重命名工具（输入文件夹路径，把其中所有图片按规则批量改名，先打印预览再执行）。

动手前必须先调用 ask_player 询问命名规则，三个选项的 label 分别为：
「规则A：拍摄日期前缀」「规则B：递增序号」「规则C：目录+序号混合」，
每个选项的 detail 都必须写清【做法】【代价】【回滚】。

等玩家选择后再开始实现。""",
    },
    {
        "name": "Markdown 表格转 CSV",
        "desc": "在 scratch/ 下写 md 表格 → CSV 转换工具，输出策略三选一",
        "task": """任务：在 galgame_coding/scratch/ 下实现一个 Markdown 表格转 CSV 的小工具（读入 .md 文件，把其中的表格提取出来输出为同名 .csv）。

动手前必须先调用 ask_player 询问输出策略，三个选项的 label 分别为：
「策略A：严格RFC4180」「策略B：宽松兼容Excel」「策略C：自动探测混合」，
每个选项的 detail 都必须写清【做法】【代价】【回滚】。

等玩家选择后再开始实现。""",
    },
]
