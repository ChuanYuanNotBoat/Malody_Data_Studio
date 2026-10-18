from copy import copy


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_hot(self, arg):
        """
        显示热门谱面排行榜（支持选择器筛选）

        用法: stb_hot [模式] [排序] [数量]
          排序: heat（热度）、donate_count（打赏数）、play_count（游玩次数）、
                recommend_count（推荐数）；均按降序排列。
          模式: -1 表示所有模式，0-9 表示指定模式；默认使用当前模式。
          数量: 默认 10，必须大于 0。
        示例: stb_hot -1 recommend_count 20
        """
        args = arg.split()
        mode = self.current_mode
        sort_field = "heat"
        limit = 10

        if len(args) > 3:
            print(colorize("用法: stb_hot [模式] [排序] [数量]", Colors.RED))
            return

        if args:
            try:
                if args[0].lstrip("-").isdigit():
                    mode = int(args[0])
                    if len(args) > 1:
                        sort_field = args[1].lower()
                        if len(args) > 2:
                            limit = int(args[2])
                else:
                    sort_field = args[0].lower()
                    if len(args) > 1:
                        mode = int(args[1])
                        if len(args) > 2:
                            limit = int(args[2])
            except ValueError:
                print(colorize("错误: 参数必须是数字", Colors.RED))
                return

        valid_fields = ["heat", "donate_count", "play_count", "recommend_count"]
        if sort_field not in valid_fields:
            print(colorize(f"错误: 排序字段必须是 {valid_fields} 之一", Colors.RED))
            return

        if mode not in self.mode_names:
            print(colorize("错误: 模式必须是 -1 或 0-9", Colors.RED))
            return
        if limit <= 0:
            print(colorize("错误: 数量必须大于 0", Colors.RED))
            return

        cursor = self.conn.cursor()
        selector = copy(self.selector)
        selector.current_mode = mode
        where_clause, params = selector.build_chart_sql_where("c")

        # Keep existing sort options usable with databases predating this column.
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(charts)")}
        if sort_field == "recommend_count" and "recommend_count" not in columns:
            print(colorize("错误: 数据库缺少 recommend_count 字段，请先更新谱面数据", Colors.RED))
            return
        recommend_expr = "COALESCE(c.recommend_count, 0)" if "recommend_count" in columns else "0"

        query = f"""
        SELECT c.cid, c.version, c.level, c.status, s.title, s.artist,
            c.creator_name, c.stabled_by_name, c.heat, c.donate_count, c.play_count, c.last_updated, c.server_exists,
            {recommend_expr} AS recommend_count
        FROM charts c
        JOIN songs s ON c.sid = s.sid
        WHERE {where_clause}
        ORDER BY COALESCE(c.{sort_field}, 0) DESC, c.cid ASC
        LIMIT ?
        """
        params.append(limit)

        cursor.execute(query, params)
        results = cursor.fetchall()

        if not results:
            print(colorize("\n没有找到符合条件的谱面", Colors.YELLOW))
            return

        if self.selector.filters["modes"]:
            mode_str = ", ".join([f"{m}({self.mode_names.get(m, '未知')})" for m in self.selector.filters["modes"]])
        elif mode != -1:
            mode_str = f"{mode}({self.mode_names.get(mode, '未知')})"
        else:
            mode_str = "所有模式"

        field_names = {"heat": "热度", "donate_count": "打赏数", "play_count": "游玩次数", "recommend_count": "推荐数"}
        print(colorize(f"\n热门谱面排行榜 (按{field_names[sort_field]}降序)", Colors.CYAN))
        print(colorize(f"模式: {mode_str}", Colors.YELLOW))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(colorize("(* 前缀表示已从服务器删除的谱面)", Colors.YELLOW))
        print(colorize("(未知表示未采集；历史游玩数 0 也可能是采集占位值)", Colors.YELLOW))
        print(get_separator())

        for i, (cid, version, level, status, title, artist, creator, stabled, heat, donate, play, updated, server_exists, recommend) in enumerate(results, 1):
            status_name = {0: "Alpha", 1: "Beta", 2: "Stable"}.get(status, "Unknown")
            rank_color = Colors.YELLOW if i <= 3 else Colors.WHITE
            if not server_exists:
                title = "*" + title

            print(f"{colorize(f'#{i}', rank_color)} {colorize(title, Colors.BOLD)} - {artist}")
            print(f"  版本: {version}, 难度: Lv.{level}, 状态: {status_name}")
            print(f"  创作者: {creator}, 稳定者: {stabled if stabled else 'N/A'}")
            donate_text = "未知" if donate is None else str(donate)
            play_text = "未知" if play is None else ("未知（历史值 0）" if play == 0 else str(play))
            print(f"  热度: {heat}, 打赏: {donate_text}, 游玩: {play_text}, 推荐: {recommend}")
            print(f"  更新: {updated}, CID: {cid}")
            print()

    setattr(cls, "do_stb_hot", db_safe_operation(do_stb_hot))
