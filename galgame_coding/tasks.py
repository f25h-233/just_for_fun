"""示例任务集：给一键启动（run.bat --menu）用的现成任务。

每个任务都满足决策化规则的示范要求：有真实路线分叉、选项结构清晰、
能完整演示"提问 → 玩家选择 → 按选择执行"的一圈。
"""

DEMO_TASKS: list[dict] = [
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
