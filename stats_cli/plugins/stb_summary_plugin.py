import os

import matplotlib.pyplot as plt

from selector import format_dual_count


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_summary(self, arg):
        """
        生成谱面综合统计报告（支持选择器筛选）
        """
        args = arg.split()
        mode = self.current_mode
        detail_level = "basic"

        if args:
            try:
                if args[0].isdigit():
                    mode = int(args[0])
                    if len(args) > 1:
                        detail_level = args[1].lower()
                else:
                    detail_level = args[0].lower()
                    if len(args) > 1 and args[1].isdigit():
                        mode = int(args[1])
            except ValueError:
                print(colorize("错误: 模式必须是数字", Colors.RED))
                return

        cursor = self.conn.cursor()
        stats = self._get_comprehensive_stats(cursor, mode, detail_level)
        self._display_summary_report(stats, mode, detail_level)

        if detail_level == "detailed":
            chart_choice = input(colorize("\n是否生成统计图表? (y/N): ", Colors.CYAN)).lower()
            if chart_choice == "y":
                self._generate_summary_charts(stats, mode)

    def _get_comprehensive_stats(self, cursor, mode, detail_level):
        stats = {}
        where_clause, params = self.selector.build_chart_sql_where("c")

        if not self.selector.filters["modes"] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else " AND c.mode = ?"
            params.append(mode)

        cursor.execute(
            f"SELECT COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) FROM charts c WHERE {where_clause}",
            params,
        )
        _row = cursor.fetchone()
        stats["total_charts"] = _row[0]
        stats["total_charts_excl"] = _row[1] or 0

        cursor.execute(
            f"SELECT COUNT(DISTINCT c.sid), COUNT(DISTINCT CASE WHEN c.server_exists = 1 THEN c.sid END) FROM charts c WHERE {where_clause}",
            params,
        )
        _row = cursor.fetchone()
        stats["unique_songs"] = _row[0]
        stats["unique_songs_excl"] = _row[1] or 0

        cursor.execute(
            f"SELECT COUNT(DISTINCT c.creator_name), COUNT(DISTINCT CASE WHEN c.server_exists = 1 THEN c.creator_name END) FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL",
            params,
        )
        _row = cursor.fetchone()
        stats["unique_creators"] = _row[0]
        stats["unique_creators_excl"] = _row[1] or 0

        cursor.execute(
            f"SELECT MIN(c.last_updated), MAX(c.last_updated) FROM charts c WHERE {where_clause} AND c.last_updated IS NOT NULL",
            params,
        )
        min_max_dates = cursor.fetchone()
        stats["first_update"] = min_max_dates[0]
        stats["last_update"] = min_max_dates[1]

        cursor.execute(
            f"SELECT AVG(c.heat), MAX(c.heat), MIN(c.heat) FROM charts c WHERE {where_clause} AND c.heat > 0",
            params,
        )
        heat_stats = cursor.fetchone()
        stats["heat_stats"] = {"avg": heat_stats[0] or 0, "max": heat_stats[1] or 0, "min": heat_stats[2] or 0}

        cursor.execute(
            f"SELECT AVG(CAST(c.level AS REAL)), MAX(CAST(c.level AS REAL)), MIN(CAST(c.level AS REAL)) FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' AND CAST(c.level AS REAL) > 0",
            params,
        )
        level_stats = cursor.fetchone()
        stats["level_stats"] = {"avg": level_stats[0] or 0, "max": level_stats[1] or 0, "min": level_stats[2] or 0}

        cursor.execute(
            f"SELECT c.status, COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) FROM charts c WHERE {where_clause} GROUP BY c.status",
            params,
        )
        stats["status_dist"] = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

        if detail_level == "detailed":
            cursor.execute(
                f"SELECT c.creator_name, COUNT(*) as count, SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) as count_excl FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL GROUP BY c.creator_name ORDER BY count DESC LIMIT 20",
                params,
            )
            stats["top_creators"] = cursor.fetchall()

            cursor.execute(
                f"SELECT c.level, COUNT(*) as count FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' AND CAST(c.level AS REAL) > 0 GROUP BY c.level ORDER BY CAST(c.level AS REAL)",
                params,
            )
            stats["level_breakdown"] = cursor.fetchall()

            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat = 0", params)
            stats["zero_heat"] = cursor.fetchone()[0]

            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat BETWEEN 1 AND 10", params)
            stats["low_heat"] = cursor.fetchone()[0]

            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat BETWEEN 11 AND 50", params)
            stats["medium_heat"] = cursor.fetchone()[0]

            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat > 50", params)
            stats["high_heat"] = cursor.fetchone()[0]

            cursor.execute(
                f"SELECT strftime('%Y-%m', c.last_updated) as month, COUNT(*) FROM charts c WHERE {where_clause} AND c.last_updated IS NOT NULL GROUP BY month ORDER BY month DESC LIMIT 12",
                params,
            )
            stats["monthly_updates"] = cursor.fetchall()

        return stats

    def _display_summary_report(self, stats, mode, detail_level):
        print(colorize("\n谱面综合统计报告", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(get_separator())

        print(colorize("\n基础概览", Colors.BOLD))
        total_excl = stats.get("total_charts_excl", stats["total_charts"])
        print(f"  总谱面数: {colorize(format_dual_count(total_excl, stats['total_charts']), Colors.GREEN)}")
        print(f"  唯一歌曲数: {format_dual_count(stats.get('unique_songs_excl', stats['unique_songs']), stats['unique_songs'])}")
        print(f"  创作者数: {format_dual_count(stats.get('unique_creators_excl', stats['unique_creators']), stats['unique_creators'])}")
        if stats["total_charts"] > total_excl:
            print(colorize("  （括号内为包含已删除谱面的数量，* 前缀表示已删除谱面）", Colors.YELLOW))

        if stats["first_update"] and stats["last_update"]:
            first_date = (
                stats["first_update"].strftime("%Y-%m-%d")
                if hasattr(stats["first_update"], "strftime")
                else stats["first_update"]
            )
            last_date = (
                stats["last_update"].strftime("%Y-%m-%d")
                if hasattr(stats["last_update"], "strftime")
                else stats["last_update"]
            )
            print(f"  数据时间范围: {first_date} 至 {last_date}")

        print(colorize("\n热度统计", Colors.BOLD))
        heat = stats["heat_stats"]
        print(f"  平均热度: {heat['avg']:.1f}")
        print(f"  最高热度: {heat['max']}")
        print(f"  最低热度: {heat['min']}")

        if stats["level_stats"]["avg"] > 0:
            print(colorize("\n难度统计", Colors.BOLD))
            level = stats["level_stats"]
            print(f"  平均难度: Lv.{level['avg']:.1f}")
            print(f"  最高难度: Lv.{level['max']}")
            print(f"  最低难度: Lv.{level['min']}")

        print(colorize("\n状态分布", Colors.BOLD))
        status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
        for status, value in stats["status_dist"].items():
            count, count_excl = value if isinstance(value, tuple) else (value, value)
            status_name = status_names.get(status, f"未知({status})")
            percentage = (count_excl / total_excl) * 100 if total_excl else 0
            print(f"  {status_name}: {format_dual_count(count_excl, count)} ({percentage:.1f}%)")

        if detail_level == "detailed":
            print(colorize("\n顶级创作者(前10)", Colors.BOLD))
            for i, row in enumerate(stats["top_creators"][:10], 1):
                creator, count = row[0], row[1]
                count_excl = row[2] if len(row) > 2 else count
                percentage = (count_excl / total_excl) * 100 if total_excl else 0
                print(f"  {i:2d}. {creator}: {format_dual_count(count_excl, count)} 谱面 ({percentage:.1f}%)")

            print(colorize("\n热度分布", Colors.BOLD))
            total_with_heat = stats["total_charts"] - stats["zero_heat"]
            if total_with_heat > 0 and stats["total_charts"] > 0:
                print(f"  无热度: {stats['zero_heat']} ({stats['zero_heat']/stats['total_charts']*100:.1f}%)")
                print(f"  低热度(1-10): {stats['low_heat']} ({stats['low_heat']/total_with_heat*100:.1f}%)")
                print(f"  中热度(11-50): {stats['medium_heat']} ({stats['medium_heat']/total_with_heat*100:.1f}%)")
                print(f"  高热度(50+): {stats['high_heat']} ({stats['high_heat']/total_with_heat*100:.1f}%)")

            if stats["monthly_updates"]:
                print(colorize("\n月度更新趋势 (最近12个月)", Colors.BOLD))
                for month, count in stats["monthly_updates"]:
                    print(f"  {month}: {count} 个谱面")

    def _generate_summary_charts(self, stats, mode):
        mode_name = self.mode_names.get(mode, "未知")
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle(f"谱面综合统计 - 模式 {mode} ({mode_name})", fontsize=16, fontweight="bold")

        status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
        status_labels = [status_names.get(s, f"未知({s})") for s in stats["status_dist"].keys()]
        status_sizes = [v[0] if isinstance(v, tuple) else v for v in stats["status_dist"].values()]
        colors1 = ["#ff9999", "#66b3ff", "#99ff99"]
        ax1.pie(status_sizes, labels=status_labels, autopct="%1.1f%%", colors=colors1, startangle=90)
        ax1.set_title("状态分布")

        heat_categories = ["无热度", "低热度", "中热度", "高热度"]
        heat_values = [
            stats.get("zero_heat", 0),
            stats.get("low_heat", 0),
            stats.get("medium_heat", 0),
            stats.get("high_heat", 0),
        ]
        colors2 = ["#cccccc", "#ffeb3b", "#ff9800", "#f44336"]

        bars = ax2.bar(heat_categories, heat_values, color=colors2)
        ax2.set_title("热度分布")
        ax2.set_ylabel("谱面数量")
        for bar, value in zip(bars, heat_values):
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f"{value}", ha="center", va="bottom")

        if stats.get("level_breakdown"):
            levels = [str(item[0]) for item in stats["level_breakdown"]]
            counts = [item[1] for item in stats["level_breakdown"]]
            ax3.bar(levels, counts, color="skyblue")
            ax3.set_title("难度分布")
            ax3.set_ylabel("谱面数量")
            ax3.tick_params(axis="x", rotation=45)
        else:
            ax3.text(0.5, 0.5, "无难度数据", ha="center", va="center", transform=ax3.transAxes)
            ax3.set_title("难度分布")

        if stats.get("top_creators"):
            creators = [item[0][:15] + "..." if len(item[0]) > 15 else item[0] for item in stats["top_creators"][:10]]
            creator_counts = [item[1] for item in stats["top_creators"][:10]]
            y_pos = range(len(creators))
            ax4.barh(y_pos, creator_counts, color="lightgreen")
            ax4.set_yticks(y_pos)
            ax4.set_yticklabels(creators)
            ax4.set_title("创作者排行(前10)")
            ax4.set_xlabel("谱面数量")
        else:
            ax4.text(0.5, 0.5, "无创作者数据", ha="center", va="center", transform=ax4.transAxes)
            ax4.set_title("创作者排行")

        plt.tight_layout()
        base_filename = f"stb_summary_mode{mode}.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor="white", bbox_inches="tight")
        plt.close()
        print(colorize(f"\n已生成综合统计图表: {filepath}", Colors.GREEN))

    setattr(cls, "do_stb_summary", db_safe_operation(do_stb_summary))
    setattr(cls, "_get_comprehensive_stats", _get_comprehensive_stats)
    setattr(cls, "_display_summary_report", _display_summary_report)
    setattr(cls, "_generate_summary_charts", _generate_summary_charts)
