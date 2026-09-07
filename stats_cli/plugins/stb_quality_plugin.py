def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_quality(self, arg):
        """
        检查数据质量（支持选择器筛选）
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
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)

        print(colorize("\n数据质量检查", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(get_separator())

        issues = []

        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.creator_name IS NULL", params)
        missing_creator = cursor.fetchone()[0]
        if missing_creator > 0:
            issues.append(f"缺失创作者: {missing_creator} 个谱面")

        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.level IS NULL", params)
        missing_level = cursor.fetchone()[0]
        if missing_level > 0:
            issues.append(f"缺失难度: {missing_level} 个谱面")

        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.last_updated IS NULL", params)
        missing_update = cursor.fetchone()[0]
        if missing_update > 0:
            issues.append(f"缺失更新时间: {missing_update} 个谱面")

        cursor.execute(
            f"SELECT COUNT(*) FROM charts c LEFT JOIN songs s ON c.sid = s.sid WHERE {where_clause} AND s.sid IS NULL",
            params,
        )
        orphan_charts = cursor.fetchone()[0]
        if orphan_charts > 0:
            issues.append(f"孤立的谱面记录: {orphan_charts} 个")

        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat < 0", params)
        negative_heat = cursor.fetchone()[0]
        if negative_heat > 0:
            issues.append(f"负热度值: {negative_heat} 个谱面")

        cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.donate_count < 0", params)
        negative_donate = cursor.fetchone()[0]
        if negative_donate > 0:
            issues.append(f"负打赏数: {negative_donate} 个谱面")

        if issues:
            print(colorize("❌ 发现数据质量问题:", Colors.RED))
            for issue in issues:
                print(f"  • {issue}")
        else:
            print(colorize("✅ 数据质量良好，未发现问题", Colors.GREEN))

        cursor.execute(
            f"SELECT COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) FROM charts c WHERE {where_clause}",
            params,
        )
        _row = cursor.fetchone()
        total_charts = _row[0]
        total_charts_excl = _row[1] or 0

        completeness_stats = []
        if total_charts > 0:
            completeness_stats.append(f"总谱面数: {total_charts_excl} ({total_charts}，含已删除)")
            creator_completeness = ((total_charts - missing_creator) / total_charts) * 100
            completeness_stats.append(f"创作者完整性: {creator_completeness:.1f}%")
            level_completeness = ((total_charts - missing_level) / total_charts) * 100
            completeness_stats.append(f"难度完整性: {level_completeness:.1f}%")
            update_completeness = ((total_charts - missing_update) / total_charts) * 100
            completeness_stats.append(f"更新时间完整性: {update_completeness:.1f}%")

        print(colorize("\n数据完整性统计", Colors.BOLD))
        for stat in completeness_stats:
            print(f"  {stat}")

    setattr(cls, "do_stb_quality", db_safe_operation(do_stb_quality))
