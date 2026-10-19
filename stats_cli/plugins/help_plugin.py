import textwrap


def install(cls, *, colorize, colors, get_separator, get_subseparator):
    Colors = colors

    def do_help(self, arg):
        """显示帮助信息"""
        if arg:
            cmd_name = arg.strip().lower()
            if hasattr(self, 'do_' + cmd_name):
                func = getattr(self, 'do_' + cmd_name)
                if func.__doc__:
                    print(colorize(f"\n{cmd_name} 命令帮助:", Colors.CYAN))
                    print(get_separator())
                    print(textwrap.dedent(func.__doc__))
                else:
                    print(colorize(f"没有找到命令 '{cmd_name}' 的帮助文档", Colors.YELLOW))
            else:
                print(colorize(f"未知命令: {cmd_name}", Colors.RED))
        else:
            print(colorize("\nMalody排行榜数据可视化工具 - 命令列表", Colors.CYAN))
            print(get_separator())
            
            commands = [
                # 基础命令
                ("ls [路径]", "列出目录内容"),
                ("mode [模式|*]", "设置或查看当前模式（*表示所有模式）"),
                ("select <选择器>", "设置筛选条件（类似MC选择器）"),
                ("repair [force]", "修复数据库问题（force强制修复）"),
                ("optimize", "优化数据库：清理冗余记录并压缩数据库"),
                
                # 玩家相关命令（支持玩家、时间、模式筛选）
                ("top [数量]", "显示顶级玩家排名"),
                ("player <玩家名> [模式]", "查看玩家基本信息"),
                ("profile <玩家名> [模式]", "查看玩家详细资料（头衔、成就、个人信息）"),
                ("history <玩家名> [模式] [天数]", "查看玩家历史排名并生成图表"),
                ("compare <玩家1> <玩家2> [...] [模式] [天数]", "比较多个玩家的排名变化"),
                ("trend <起始日期> [--mode 模式] [--fields 字段] [--match 窗口] [--rank-range 范围]", "统计玩家数据变化趋势"),
                ("search <关键词> [类型] [模式]", "搜索玩家/谱面/创作者"),
                
                # 谱面相关命令（支持难度、时间、模式筛选）
                ("stb_stats [模式]", "谱面基础统计"),
                ("stb_summary [模式] [级别]", "谱面综合统计报告"),
                ("stb_hot [模式] [排序] [数量]", "热门谱面排行榜（推荐数排序: recommend_count）"),
                ("stb_pie [模式] [类型]", "生成谱面分布饼状图"),
                ("stb_recent [天数] [模式] [数量]", "查询最近更新的谱面"),
                ("stb_quality [模式]", "检查数据质量"),
                ("stb_trends [模式] [周期]", "分析谱面数据趋势"),
                ("stb_compare [模式列表]", "比较不同模式的谱面数据"),
                ("stb_stabled_by <玩家名> [模式] [数量]", "查询玩家作为稳定者的谱面统计"),
                ("stb_top_stabilizers [模式] [数量]", "显示顶级稳定者排行榜"),
                ("stb_creator_details <创作者名> [模式] [状态]", "查看指定创作者的所有谱面统计"),
                ("stb_creator_trends <创作者名> [周期]", "分析特定创作者的谱面更新趋势"),

                # 爬虫状态与控制
                ("update [--leaderboard] [--player] [--stb] [--once] [--limit N] [--rpm N]", "更新数据（调用外部爬虫）"),
                ("crawl_status", "查看各爬虫的进度状态"),

                # 其他命令
                ("alias <原名> <新名>", "设置玩家别名"),
                ("reload [all|module <name>|command <name>]", "热重载命令/模块"),
                ("export <类型> [选项]", "导出数据为CSV/XLSX（类型：top, history, chart, song, profile）"),
                ("help [命令]", "显示帮助信息"),
                ("exit/quit", "退出程序")
            ]
            
            for cmd, desc in commands:
                print(f"  {colorize(cmd, Colors.GREEN):<45} {desc}")
            print(colorize("\n选择器格式说明:", Colors.CYAN))
            print(get_subseparator())
            print("  @p[玩家1,玩家2]    - 选择玩家（支持名称或UID）")
            print("  @d[难度范围]      - 选择难度（如 5, 5-10）")
            print("  @t[时间范围]      - 选择时间（如 7d, 30d）") 
            print("  @m[模式列表]      - 选择模式（如 0,3,5）")
            print("  @s[状态列表]      - 选择状态（如 0,2 - 0=Alpha,1=Beta,2=Stable）")
            print("  @*                - 选择所有（清除筛选）")
            
            print(colorize("\n命令筛选支持:", Colors.CYAN))
            print(get_subseparator())
            print("  玩家命令: 支持玩家、时间、模式筛选")
            print("  谱面命令: 支持难度、时间、模式、状态筛选")
            
            print(colorize("\n模式编号对应表:", Colors.CYAN))
            print(get_subseparator())
            for mode_id, mode_name in self.mode_names.items():
                print(f"  {mode_id}: {mode_name}")
            
            print(colorize("\n输入 'help <命令名>' 查看具体命令的详细说明", Colors.YELLOW))


    setattr(cls, "do_help", do_help)

