def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_hot(self, arg):
        """
        显示热门谱面排行榜（支持选择器筛选）
        """
        args = arg.split()
        mode = self.current_mode
        sort_field = "heat"
        limit = 10

        if args:
            try:
                if args[0].isdigit():
                    mode = int(args[0])
                    if len(args) > 1:
                        sort_field = args[1].lower()
                        if len(args) > 2:
                            limit = int(args[2])
                else:
                    sort_field = args[0].lower()
                    if len(args) > 1 and args[1].isdigit():
                        mode = int(args[1])
                        if len(args) > 2:
                            limit = int(args[2])
            except ValueError:
                print(colorize("错误: 参数必须是数字", Colors.RED))
                return

        valid_fields = ["heat", "donate_count", "play_count"]
        if sort_field not in valid_fields:
            print(colorize(f"错误: 排序字段必须是 {valid_fields} 之一", Colors.RED))
            return

        cursor = self.conn.cursor()
        where_clause, params = self.selector.build_chart_sql_where("c")

        if not self.selector.filters["modes"] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)

        query = f"""
        SELECT c.cid, c.version, c.level, c.status, s.title, s.artist,
            c.creator_name, c.stabled_by_name, c.heat, c.donate_count, c.play_count, c.last_updated, c.server_exists
        FROM charts c
        JOIN songs s ON c.sid = s.sid
        WHERE {where_clause}
        ORDER BY c.{sort_field} DESC
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
        elif self.selector.current_mode != -1:
            mode_str = f"{self.selector.current_mode}({self.mode_names.get(self.selector.current_mode, '未知')})"
        else:
            mode_str = "所有模式"

        field_names = {"heat": "热度", "donate_count": "打赏数", "play_count": "游玩次数"}
        print(colorize(f"\n热门谱面排行榜 (按{field_names[sort_field]}排序)", Colors.CYAN))
        print(colorize(f"模式: {mode_str}", Colors.YELLOW))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(colorize("(* 前缀表示已从服务器删除的谱面)", Colors.YELLOW))
        print(get_separator())

        for i, (cid, version, level, status, title, artist, creator, stabled, heat, donate, play, updated, server_exists) in enumerate(results, 1):
            status_name = {0: "Alpha", 1: "Beta", 2: "Stable"}.get(status, "Unknown")
            rank_color = Colors.YELLOW if i <= 3 else Colors.WHITE
            if not server_exists:
                title = "*" + title

            print(f"{colorize(f'#{i}', rank_color)} {colorize(title, Colors.BOLD)} - {artist}")
            print(f"  版本: {version}, 难度: Lv.{level}, 状态: {status_name}")
            print(f"  创作者: {creator}, 稳定者: {stabled if stabled else 'N/A'}")
            print(f"  热度: {heat}, 打赏: {donate}, 游玩: {play}")
            print(f"  更新: {updated}, CID: {cid}")
            print()

    setattr(cls, "do_stb_hot", db_safe_operation(do_stb_hot))
