from selector import format_dual_count


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_stats(self, arg):
        """
        谱面基础统计（支持选择器筛选）
        """
        args = arg.split()
        mode = self.current_mode
        if args:
            try:
                mode = int(args[0])
            except ValueError:
                print(colorize("错误: 模式必须是数字", Colors.RED))
                return

        cursor = self.conn.cursor()
        where_clause, params = self.selector.build_chart_sql_where("c")

        if not self.selector.filters["modes"] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else " AND c.mode = ?"
            params.append(mode)

        stats = self._get_chart_stats(cursor, where_clause, params)

        if self.selector.filters["modes"]:
            mode_str = ", ".join([f"{m}({self.mode_names.get(m, '未知')})" for m in self.selector.filters["modes"]])
        elif self.selector.current_mode != -1:
            mode_str = f"{self.selector.current_mode}({self.mode_names.get(self.selector.current_mode, '未知')})"
        else:
            mode_str = "所有模式"

        self._display_chart_stats(stats, mode_str)

    def _get_chart_stats(self, cursor, where_clause, params):
        stats = {}

        try:
            cursor.execute(
                f"SELECT COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) FROM charts c WHERE {where_clause}",
                params,
            )
            _row = cursor.fetchone()
            stats["total_charts"] = _row[0] or 0
            stats["total_charts_excl"] = _row[1] or 0

            cursor.execute(
                f"SELECT c.status, COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) FROM charts c WHERE {where_clause} GROUP BY c.status",
                params,
            )
            status_results = cursor.fetchall()
            stats["status_dist"] = {0: 0, 1: 0, 2: 0}
            for status, count, count_excl in status_results:
                if status in [0, 1, 2]:
                    stats["status_dist"][status] = (count, count_excl)

            cursor.execute(
                f"SELECT c.level, COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' GROUP BY c.level ORDER BY CAST(c.level AS REAL)",
                params,
            )
            stats["level_dist"] = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

            cursor.execute(
                f"SELECT c.creator_name, COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL GROUP BY c.creator_name ORDER BY COUNT(*) DESC LIMIT 10",
                params,
            )
            stats["top_creators"] = cursor.fetchall()

            cursor.execute(
                f"SELECT AVG(c.heat), MAX(c.heat), AVG(c.donate_count), MAX(c.donate_count) FROM charts c WHERE {where_clause}",
                params,
            )
            heat_stats = cursor.fetchone()
            stats["heat_avg"], stats["heat_max"], stats["donate_avg"], stats["donate_max"] = heat_stats or (
                0,
                0,
                0,
                0,
            )
        except Exception as e:
            print(colorize(f"获取统计信息时出错: {e}", Colors.RED))
            stats = {
                "total_charts": 0,
                "status_dist": {0: 0, 1: 0, 2: 0},
                "level_dist": {},
                "top_creators": [],
                "heat_avg": 0,
                "heat_max": 0,
                "donate_avg": 0,
                "donate_max": 0,
            }

        return stats

    def _display_chart_stats(self, stats, mode_str):
        print(colorize(f"\n谱面统计 - 模式 {mode_str}", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(get_separator())

        if not stats or stats["total_charts"] == 0:
            print(colorize("没有找到符合条件的谱面", Colors.YELLOW))
            return

        print(f"总谱面数: {colorize(format_dual_count(stats.get('total_charts_excl', stats['total_charts']), stats['total_charts']), Colors.GREEN)}")
        if stats['total_charts'] > stats.get('total_charts_excl', 0):
            print(colorize("（括号内为包含已删除谱面的数量，* 前缀表示已删除谱面）", Colors.YELLOW))

        if stats["status_dist"]:
            print(f"\n{colorize('状态分布:', Colors.BOLD)}")
            status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
            for status in [0, 1, 2]:
                value = stats["status_dist"].get(status, 0)
                count, count_excl = value if isinstance(value, tuple) else (value, value)
                status_name = status_names.get(status, f"未知({status})")
                print(f"  {status_name}: {format_dual_count(count_excl, count)}")

        if stats["level_dist"]:
            print(f"\n{colorize('难度分布:', Colors.BOLD)}")
            for level, value in sorted(stats["level_dist"].items(), key=lambda x: float(x[0])):
                count, count_excl = value if isinstance(value, tuple) else (value, value)
                print(f"  Lv.{level}: {format_dual_count(count_excl, count)}")

        if stats["top_creators"]:
            print(f"\n{colorize('热门创作者:', Colors.BOLD)}")
            for row in stats["top_creators"]:
                creator, count = row[0], row[1]
                count_excl = row[2] if len(row) > 2 else count
                print(f"  {creator}: {format_dual_count(count_excl, count)} 个谱面")

        print(f"\n{colorize('热度统计:', Colors.BOLD)}")
        print(f"  平均热度: {stats['heat_avg']:.1f}")
        print(f"  最高热度: {stats['heat_max']}")
        print(f"  平均打赏: {stats['donate_avg']:.1f}")
        print(f"  最多打赏: {stats['donate_max']}")

    setattr(cls, "do_stb_stats", db_safe_operation(do_stb_stats))
    setattr(cls, "_get_chart_stats", _get_chart_stats)
    setattr(cls, "_display_chart_stats", _display_chart_stats)
