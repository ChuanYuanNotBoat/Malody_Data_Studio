import os
import sqlite3
from datetime import datetime

import matplotlib.pyplot as plt

from selector import format_dual_count


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_top_stabilizers(self, arg):
        """
        显示顶级稳定者排行榜（审核上架谱面最多的玩家）
        """
        args = arg.split()
        mode = -1
        limit = 20

        if args:
            try:
                mode = int(args[0])
                if mode not in self.mode_names:
                    print(colorize("错误: 无效的模式编号", Colors.RED))
                    return
                if len(args) > 1:
                    limit = int(args[1])
            except ValueError:
                print(colorize("错误: 请输入有效的数字", Colors.RED))
                return

        if limit <= 0:
            print(colorize("错误: 数量必须大于0", Colors.RED))
            return

        cursor = self.conn.cursor()

        try:
            where_conditions = ["c.stabled_by_name IS NOT NULL", "c.status = 2"]
            params = []

            if mode != -1:
                where_conditions.append("c.mode = ?")
                params.append(mode)

            where_clause = " AND ".join(where_conditions)
            query = f"""
            SELECT
                c.stabled_by_name,
                COUNT(*) as stable_count,
                SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) as stable_count_excl,
                AVG(CASE WHEN c.server_exists = 1 THEN c.heat END) as avg_heat,
                MAX(c.heat) as max_heat,
                MIN(c.last_updated) as first_stable,
                MAX(c.last_updated) as last_stable
            FROM charts c
            WHERE {where_clause}
            GROUP BY c.stabled_by_name
            ORDER BY stable_count DESC, avg_heat DESC
            LIMIT ?
            """
            params.append(limit)

            cursor.execute(query, params)
            results = cursor.fetchall()

            if not results:
                mode_str = "所有模式" if mode == -1 else f"模式 {mode}"
                print(colorize(f"\n在{mode_str}中没有找到稳定者数据", Colors.YELLOW))
                return

            mode_str = "所有模式" if mode == -1 else f"模式 {mode} ({self.mode_names.get(mode, '未知')})"
            print(colorize("\n顶级稳定者排行榜", Colors.CYAN))
            print(colorize(f"模式: {mode_str}", Colors.YELLOW))
            print(get_separator())

            header_format = "{:<4} {:<20} {:<10} {:<10} {:<10} {:<12} {:<12}"
            print(
                colorize(
                    header_format.format("排名", "稳定者", "稳定谱面", "平均热度", "最高热度", "首次稳定", "最后稳定"),
                    Colors.BOLD,
                )
            )
            print(get_separator())

            for i, (stabilizer, count, count_excl, avg_heat, max_heat, first_stable, last_stable) in enumerate(results, 1):
                display_stabilizer = stabilizer if len(stabilizer) <= 20 else stabilizer[:17] + "..."

                def format_date(date_value):
                    if not date_value:
                        return "未知"
                    if isinstance(date_value, datetime):
                        return date_value.strftime("%Y-%m-%d")
                    if isinstance(date_value, str):
                        return date_value[:10] if len(date_value) >= 10 else date_value
                    return str(date_value)

                first_date = format_date(first_stable)
                last_date = format_date(last_stable)

                print(
                    header_format.format(
                        f"#{i}",
                        display_stabilizer,
                        format_dual_count(count_excl, count),
                        f"{avg_heat:.1f}" if avg_heat else "N/A",
                        f"{max_heat:.0f}" if max_heat else "N/A",
                        first_date,
                        last_date,
                    )
                )

            print(get_separator())

            total_stable = sum(row[1] for row in results)
            total_stable_excl = sum(row[2] for row in results)
            avg_stable = total_stable_excl / len(results)
            max_stable = max(row[2] for row in results)

            print(colorize("\n统计信息:", Colors.BOLD))
            print(f"  总稳定谱面数: {format_dual_count(total_stable_excl, total_stable)}")
            print(colorize("  (括号内为包含已删除谱面的数量，其余统计已排除已删除谱面)", Colors.YELLOW))
            print(f"  平均每人稳定谱面: {avg_stable:.1f}")
            print(f"  最高稳定谱面数: {max_stable}")

            chart_choice = input(colorize("\n是否生成统计图表? (y/N): ", Colors.CYAN)).lower()
            if chart_choice == "y":
                self._generate_top_stabilizers_chart(results, mode_str)

        except sqlite3.Error as e:
            print(colorize(f"数据库错误: {e}", Colors.RED))
        except Exception as e:
            print(colorize(f"操作错误: {e}", Colors.RED))

    def _generate_top_stabilizers_chart(self, results, mode_str):
        if not results:
            return

        stabilizers = [row[0] for row in results]
        counts = [row[1] for row in results]
        avg_heats = [row[2] if row[2] else 0 for row in results]
        max_heats = [row[3] if row[3] else 0 for row in results]
        display_stabilizers = [s[:12] + "..." if len(s) > 15 else s for s in stabilizers]

        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(20, 12))
        fig.suptitle(f"顶级稳定者统计\n模式: {mode_str}", fontsize=16, fontweight="bold")

        y_pos = range(len(display_stabilizers))
        bars = ax1.barh(y_pos, counts, color="lightgreen", alpha=0.7)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels(display_stabilizers)
        ax1.set_xlabel("稳定谱面数量")
        ax1.set_title("稳定谱面数量排行")
        for bar, count in zip(bars, counts):
            width = bar.get_width()
            ax1.text(width + 0.1, bar.get_y() + bar.get_height() / 2, f"{count}", ha="left", va="center", fontsize=9)

        bars2 = ax2.barh(y_pos, avg_heats, color="lightcoral", alpha=0.7)
        ax2.set_yticks(y_pos)
        ax2.set_yticklabels(display_stabilizers)
        ax2.set_xlabel("平均热度")
        ax2.set_title("稳定谱面平均热度")
        for bar, heat in zip(bars2, avg_heats):
            width = bar.get_width()
            ax2.text(width + 0.1, bar.get_y() + bar.get_height() / 2, f"{heat:.1f}", ha="left", va="center", fontsize=9)

        bars3 = ax3.barh(y_pos, max_heats, color="gold", alpha=0.7)
        ax3.set_yticks(y_pos)
        ax3.set_yticklabels(display_stabilizers)
        ax3.set_xlabel("最高热度")
        ax3.set_title("稳定谱面最高热度")
        for bar, heat in zip(bars3, max_heats):
            width = bar.get_width()
            ax3.text(width + 0.1, bar.get_y() + bar.get_height() / 2, f"{heat:.0f}", ha="left", va="center", fontsize=9)

        scatter = ax4.scatter(counts, avg_heats, s=100, c=max_heats, cmap="viridis", alpha=0.7)
        ax4.set_xlabel("稳定谱面数量")
        ax4.set_ylabel("平均热度")
        ax4.set_title("稳定谱面数量 vs 平均热度 (颜色表示最高热度)")
        ax4.grid(True, alpha=0.3)
        for stabilizer, count, heat in zip(display_stabilizers, counts, avg_heats):
            ax4.annotate(stabilizer, (count, heat), xytext=(5, 5), textcoords="offset points", fontsize=8, alpha=0.7)

        cbar = plt.colorbar(scatter, ax=ax4)
        cbar.set_label("最高热度")

        plt.tight_layout()
        base_filename = "stb_top_stabilizers.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor="white", bbox_inches="tight")
        plt.close()
        print(colorize(f"\n已生成顶级稳定者统计图表: {filepath}", Colors.GREEN))

    setattr(cls, "do_stb_top_stabilizers", db_safe_operation(do_stb_top_stabilizers))
    setattr(cls, "_generate_top_stabilizers_chart", _generate_top_stabilizers_chart)
