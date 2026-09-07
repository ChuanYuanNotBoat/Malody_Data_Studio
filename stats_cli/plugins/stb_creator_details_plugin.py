import copy
import os
import re

import matplotlib.pyplot as plt

from selector import format_dual_count


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_creator_details(self, arg):
        """
        查看指定创作者的所有谱面统计
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入创作者名", Colors.RED))
            return
        creator = args[0]
        mode = self.current_mode
        status = None
        if len(args) > 1:
            try:
                mode = int(args[1])
            except Exception:
                pass
        if len(args) > 2:
            try:
                status = int(args[2])
            except Exception:
                pass

        selector = copy.deepcopy(self.selector)
        selector.set_filters(players=[creator])
        if mode != -1:
            selector.set_filters(modes=[mode])
        if status is not None:
            selector.set_filters(statuses=[status])

        where_clause, params = selector.build_chart_sql_where("c")
        cursor = self.conn.cursor()

        query_total = f"""
        SELECT COUNT(*),
               SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END),
               COUNT(DISTINCT c.mode),
               AVG(CASE WHEN c.server_exists = 1 THEN c.heat END),
               AVG(CASE WHEN c.server_exists = 1 THEN CAST(c.level AS REAL) END)
        FROM charts c
        WHERE {where_clause}
        """
        cursor.execute(query_total, params)
        total, total_excl, modes_count, avg_heat, avg_level = cursor.fetchone()
        total_excl = total_excl if total_excl is not None else 0

        query_status = f"""
        SELECT c.status, COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END)
        FROM charts c
        WHERE {where_clause}
        GROUP BY c.status
        """
        cursor.execute(query_status, params)
        status_dist = cursor.fetchall()

        query_mode = f"""
        SELECT c.mode, COUNT(*), SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END)
        FROM charts c
        WHERE {where_clause}
        GROUP BY c.mode
        ORDER BY c.mode
        """
        cursor.execute(query_mode, params)
        mode_dist = cursor.fetchall()

        print(colorize(f"\n创作者详情: {creator}", Colors.CYAN))
        print(get_separator())
        print(f"总谱面数: {colorize(format_dual_count(total_excl, total), Colors.GREEN)}")
        if total > total_excl:
            print(colorize("(括号内为包含已删除谱面的数量，* 前缀表示已删除谱面)", Colors.YELLOW))
        print(f"涉及模式数: {modes_count}")
        print(f"平均热度: {avg_heat:.1f}")
        print(f"平均难度: {avg_level:.1f}")

        if status_dist:
            print(colorize("\n状态分布:", Colors.BOLD))
            status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
            for status_value, count, count_excl in status_dist:
                print(f"  {status_names.get(status_value, status_value)}: {format_dual_count(count_excl, count)}")

        if mode_dist:
            print(colorize("\n模式分布:", Colors.BOLD))
            for mode_value, count, count_excl in mode_dist:
                mode_name = self.mode_names.get(mode_value, "未知")
                print(f"  模式 {mode_value}({mode_name}): {format_dual_count(count_excl, count)}")

        show_list = input(colorize("\n是否显示谱面列表? (y/N): ", Colors.CYAN)).lower()
        if show_list == "y":
            query_list = f"""
            SELECT c.cid, s.title, c.version, c.level, c.status, c.heat, c.server_exists
            FROM charts c JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.heat DESC LIMIT 50
            """
            cursor.execute(query_list, params)
            charts = cursor.fetchall()
            print(colorize("\n谱面列表 (前50):", Colors.BOLD))
            for cid, title, version, level, status_value, heat, server_exists in charts:
                status_name = {0: "A", 1: "B", 2: "S"}.get(status_value, "?")
                if not server_exists:
                    title = "*" + title
                print(f"  CID:{cid} [{status_name}] Lv.{level} {title} ({version}) - 热度:{heat}")

        chart_choice = input(colorize("\n是否生成创作者统计图表? (y/N): ", Colors.CYAN)).lower()
        if chart_choice == "y":
            self._generate_creator_chart(creator, status_dist, mode_dist)

    def _generate_creator_chart(self, creator, status_dist, mode_dist):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        fig.suptitle(f"创作者统计- {creator}", fontsize=14)

        if status_dist:
            status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
            labels = [status_names.get(row[0], str(row[0])) for row in status_dist]
            counts = [row[1] for row in status_dist]
            ax1.pie(counts, labels=labels, autopct="%1.1f%%", startangle=90)
            ax1.set_title("状态分布")
        else:
            ax1.text(0.5, 0.5, "无数据", ha="center", va="center", transform=ax1.transAxes)

        if mode_dist:
            mode_names = {
                0: "Key",
                1: "Step",
                2: "DJ",
                3: "Catch",
                4: "Pad",
                5: "Taiko",
                6: "Ring",
                7: "Slide",
                8: "Live",
                9: "Cube",
            }
            labels = [mode_names.get(row[0], str(row[0])) for row in mode_dist]
            counts = [row[1] for row in mode_dist]
            ax2.bar(labels, counts, color="lightblue")
            ax2.set_title("模式分布")
            ax2.set_ylabel("谱面数量")
        else:
            ax2.text(0.5, 0.5, "无数据", ha="center", va="center", transform=ax2.transAxes)

        plt.tight_layout()
        safe_creator = re.sub(r"[^\w]", "_", creator)
        filename = self.get_unique_filename(f"creator_{safe_creator}.png", "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor="white")
        plt.close()
        print(colorize(f"已生成创作者统计图表: {filepath}", Colors.GREEN))

    setattr(cls, "do_stb_creator_details", db_safe_operation(do_stb_creator_details))
    setattr(cls, "_generate_creator_chart", _generate_creator_chart)
