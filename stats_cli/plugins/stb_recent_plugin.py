from datetime import datetime, timedelta


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_recent(self, arg):
        """
        查询最近更新的谱面（支持选择器筛选）
        """
        args = arg.split()
        days = 7
        mode = self.current_mode
        limit = 10

        if args:
            try:
                days = int(args[0])
                if len(args) > 1:
                    mode = int(args[1])
                    if len(args) > 2:
                        limit = int(args[2])
            except ValueError:
                print(colorize("错误: 参数必须是数字", Colors.RED))
                return

        cursor = self.conn.cursor()
        where_clause, params = self.selector.build_chart_sql_where("c")

        if not self.selector.filters["time_range"]:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            where_clause += " AND c.last_updated >= ?" if where_clause != "1=1" else "c.last_updated >= ?"
            params.append(start_date)

        if not self.selector.filters["modes"] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)

        query = f"""
        SELECT c.cid, c.version, c.level, c.status, s.title, s.artist,
            c.creator_name, c.stabled_by_name, c.heat, c.donate_count, c.play_count, c.last_updated, c.crawl_time, c.server_exists
        FROM charts c
        JOIN songs s ON c.sid = s.sid
        WHERE {where_clause}
        ORDER BY c.last_updated DESC
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

        print(colorize("\n最近更新的谱面", Colors.CYAN))
        print(colorize(f"模式: {mode_str}", Colors.YELLOW))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(colorize("(* 前缀表示已从服务器删除的谱面)", Colors.YELLOW))
        print(get_separator())

        for cid, version, level, status, title, artist, creator, stabled, heat, donate, play, last_updated, crawl_time, server_exists in results:
            status_name = {0: "Alpha", 1: "Beta", 2: "Stable"}.get(status, "Unknown")
            days_ago = (datetime.now() - last_updated).days if last_updated else "未知"
            if not server_exists:
                title = "*" + title

            print(f"{colorize(title, Colors.BOLD)} - {artist}")
            print(f"  版本: {version}, 难度: Lv.{level}, 状态: {status_name}")
            print(f"  创作者: {creator}, 稳定者: {stabled if stabled else 'N/A'}")
            print(f"  热度: {heat}, 打赏: {donate}, 游玩: {play}")
            print(f"  最后更新: {last_updated} ({days_ago}天前), CID: {cid}")
            print()

    setattr(cls, "do_stb_recent", db_safe_operation(do_stb_recent))
