import os
import re

import matplotlib.pyplot as plt

from selector import format_dual_count


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_compare(self, arg):
        """
        比较不同模式的谱面数据（支持选择器筛选）
        """
        if arg:
            try:
                modes = [int(m.strip()) for m in arg.split(",")]
                for mode in modes:
                    if mode not in self.mode_names or mode == -1:
                        print(colorize(f"错误: 模式 {mode} 不存在", Colors.RED))
                        return
            except ValueError:
                print(colorize("错误: 模式必须是数字", Colors.RED))
                return
        else:
            modes = list(self.mode_names.keys())
            modes.remove(-1)

        cursor = self.conn.cursor()

        print(colorize("\n模式比较分析", Colors.CYAN))
        print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
        print(get_separator())

        comparison_data = []

        for mode in modes:
            where_clause, params = self.selector.build_chart_sql_where("c")

            if "c.mode IN" in where_clause or "c.mode =" in where_clause:
                where_clause = re.sub(r"c\.mode IN \(.*?\)|c\.mode = \?", "c.mode = ?", where_clause)
                params = [p for p in params if not isinstance(p, int) or p not in modes]
                params.append(mode)
            else:
                where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
                params.append(mode)

            cursor.execute(
                f"SELECT COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) FROM charts c WHERE {where_clause}",
                params,
            )
            _row = cursor.fetchone()
            total_charts = _row[0]
            total_charts_excl = _row[1] or 0

            cursor.execute(
                f"SELECT COUNT(DISTINCT CASE WHEN c.server_exists = 1 THEN c.creator_name END) FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL",
                params,
            )
            unique_creators = cursor.fetchone()[0]

            cursor.execute(
                f"SELECT AVG(CASE WHEN c.server_exists = 1 THEN c.heat END) FROM charts c WHERE {where_clause} AND c.heat > 0",
                params,
            )
            avg_heat = cursor.fetchone()[0] or 0

            cursor.execute(
                f"SELECT AVG(CASE WHEN c.server_exists = 1 THEN CAST(c.level AS REAL) END) FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' AND CAST(c.level AS REAL) > 0",
                params,
            )
            avg_level = cursor.fetchone()[0] or 0

            cursor.execute(
                f"SELECT COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) FROM charts c WHERE {where_clause} AND c.status = 2",
                params,
            )
            _row = cursor.fetchone()
            stable_charts = _row[0]
            stable_charts_excl = _row[1] or 0

            mode_name = self.mode_names.get(mode, "未知")
            comparison_data.append(
                {
                    "mode": mode,
                    "name": mode_name,
                    "total_charts": total_charts,
                    "total_charts_excl": total_charts_excl,
                    "unique_creators": unique_creators,
                    "avg_heat": avg_heat,
                    "avg_level": avg_level,
                    "stable_charts": stable_charts,
                    "stable_charts_excl": stable_charts_excl,
                    "stability_rate": (stable_charts_excl / total_charts_excl * 100) if total_charts_excl > 0 else 0,
                }
            )

        comparison_data.sort(key=lambda x: x["total_charts"], reverse=True)

        header = f"{'模式':<10} {'模式名':<12} {'总谱面':<8} {'创作者':<8} {'平均热度':<10} {'平均难度':<10} {'稳定率':<8}"
        print(header)
        print(colorize("(总谱面列: 括号内为包含已删除谱面的数量，其余统计已排除已删除谱面)", Colors.YELLOW))
        print(get_separator())

        for data in comparison_data:
            mode_str = f"{data['mode']} ({data['name']})"
            print(
                f"{mode_str:<10} {data['name']:<12} {format_dual_count(data['total_charts_excl'], data['total_charts']):<8} {data['unique_creators']:<8} "
                f"{data['avg_heat']:<10.1f} {data['avg_level']:<10.1f} {data['stability_rate']:<8.1f}%"
            )

        if len(modes) > 1:
            self._generate_comparison_chart(comparison_data)

    def _generate_comparison_chart(self, comparison_data):
        modes = [f"{d['mode']}\n({d['name']})" for d in comparison_data]
        total_charts = [d["total_charts"] for d in comparison_data]
        unique_creators = [d["unique_creators"] for d in comparison_data]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

        bars1 = ax1.bar(modes, total_charts, color="lightblue", alpha=0.7)
        ax1.set_title("各模式总谱面数比较\n筛选条件: " + self.selector.get_current_selection())
        ax1.set_ylabel("谱面数量")
        ax1.tick_params(axis="x", rotation=45)

        for bar in bars1:
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f"{int(height)}", ha="center", va="bottom")

        bars2 = ax2.bar(modes, unique_creators, color="lightgreen", alpha=0.7)
        ax2.set_title("各模式创作者数比较\n筛选条件: " + self.selector.get_current_selection())
        ax2.set_ylabel("创作者数量")
        ax2.tick_params(axis="x", rotation=45)

        for bar in bars2:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width() / 2.0, height + 0.1, f"{int(height)}", ha="center", va="bottom")

        plt.tight_layout()
        base_filename = "stb_mode_comparison.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor="white")
        plt.close()
        print(colorize(f"\n已生成模式比较图表: {filepath}", Colors.GREEN))

    setattr(cls, "do_stb_compare", db_safe_operation(do_stb_compare))
    setattr(cls, "_generate_comparison_chart", _generate_comparison_chart)
