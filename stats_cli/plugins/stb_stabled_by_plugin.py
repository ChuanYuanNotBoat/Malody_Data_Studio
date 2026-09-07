import os
import re

import matplotlib.pyplot as plt
import numpy as np


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def do_stb_stabled_by(self, arg):
        """
        查询玩家作为稳定者的谱面统计（支持选择器筛选）
        """
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入玩家名", Colors.RED))
            return

        player_name = args[0]
        mode = self.current_mode
        limit = 20

        if len(args) > 1:
            try:
                mode = int(args[1])
                if len(args) > 2:
                    limit = int(args[2])
            except ValueError:
                print(colorize("错误: 请输入有效的数字", Colors.RED))
                return

        cursor = self.conn.cursor()
        where_conditions = ["c.stabled_by_name LIKE ?"]
        params = [f"%{player_name}%"]

        if mode != -1:
            where_conditions.append("c.mode = ?")
            params.append(mode)

        selector_where, selector_params = self.selector.build_chart_sql_where("c")
        if selector_where != "1=1":
            where_conditions.append(f"({selector_where})")
            params.extend(selector_params)

        where_clause = " AND ".join(where_conditions)

        query = f"""
        SELECT c.cid, s.title, s.artist, c.version, c.level, c.mode, c.status,
               c.heat, c.donate_count, c.play_count, c.last_updated, c.server_exists
        FROM charts c
        JOIN songs s ON c.sid = s.sid
        WHERE {where_clause}
        ORDER BY c.heat DESC
        LIMIT ?
        """
        params.append(limit)

        cursor.execute(query, params)
        results = cursor.fetchall()

        if not results:
            print(colorize(f"\n没有找到 {player_name} 作为稳定者的谱面", Colors.YELLOW))
            return

        print(colorize(f"\n{player_name} 作为稳定者的谱面", Colors.CYAN))
        print(colorize(f"模式: {mode if mode != -1 else '所有'}", Colors.YELLOW))
        print(get_separator())

        print(colorize("(* 前缀表示已从服务器删除的谱面)", Colors.YELLOW))

        for cid, title, artist, version, level, m, status, heat, donate, play, updated, server_exists in results:
            status_name = {0: "Alpha", 1: "Beta", 2: "Stable"}.get(status, "Unknown")
            mode_name = self.mode_names.get(m, "未知")
            if not server_exists:
                title = "*" + title
            print(f"{title} - {artist}")
            print(f"  CID:{cid} 模式:{m}({mode_name}) 难度:Lv.{level} 状态:{status_name}")
            print(f"  热度:{heat} 打赏:{donate} 游玩:{play}")
            print()

        print(get_separator())

        total = len(results)
        modes_dist = {}
        status_dist = {}
        for row in results:
            mode_value = row[5]
            modes_dist[mode_value] = modes_dist.get(mode_value, 0) + 1
            status_value = row[6]
            status_dist[status_value] = status_dist.get(status_value, 0) + 1

        deleted_count = sum(1 for row in results if not row[11])
        total_line = f"总计: {total} 个谱面 (包含已删除)"
        if deleted_count:
            total_line += f"，其中已删除 {deleted_count} 个"
        print(total_line)
        print("模式分布:", ", ".join([f"{self.mode_names.get(m, '未知')}:{c}" for m, c in modes_dist.items()]))
        print("状态分布:", ", ".join([f"{['Alpha', 'Beta', 'Stable'][s]}:{c}" for s, c in status_dist.items()]))

        chart_choice = input(colorize("\n是否生成统计图表? (y/N): ", Colors.CYAN)).lower()
        if chart_choice == "y":
            self._generate_stabled_by_chart(results, player_name, f"模式 {mode if mode != -1 else '所有'}", total)

    def _generate_stabled_by_chart(self, results, player_name, mode_str, total_count):
        if not results:
            return

        titles = [("*" if not row[11] else "") + row[1] for row in results]
        heats = [row[7] or 0 for row in results]
        levels = [row[4] for row in results]
        display_titles = [t[:17] + "..." if len(t) > 20 else t for t in titles]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 8))
        fig.suptitle(
            f"{player_name} 作为稳定者的谱面统计\n模式: {mode_str} | 总谱面数: {total_count}",
            fontsize=14,
            fontweight="bold",
        )

        y_pos = range(len(display_titles))
        bars = ax1.barh(y_pos, heats, color="lightcoral", alpha=0.7)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels(display_titles)
        ax1.set_xlabel("热度")
        ax1.set_title("谱面热度分布")

        for bar, heat in zip(bars, heats):
            width = bar.get_width()
            ax1.text(width + 0.1, bar.get_y() + bar.get_height() / 2, f"{heat}", ha="left", va="center", fontsize=9)

        level_counts = {}
        for level in levels:
            if level:
                level_counts[level] = level_counts.get(level, 0) + 1

        if level_counts:
            level_labels = [f"Lv.{lvl}" for lvl in level_counts.keys()]
            level_values = list(level_counts.values())
            palette = plt.cm.Set3(np.linspace(0, 1, len(level_labels)))
            _, _, autotexts = ax2.pie(level_values, labels=level_labels, autopct="%1.1f%%", colors=palette, startangle=90)
            for autotext in autotexts:
                autotext.set_color("white")
                autotext.set_fontweight("bold")
            ax2.set_title("难度分布")
        else:
            ax2.text(0.5, 0.5, "无难度数据", ha="center", va="center", transform=ax2.transAxes)
            ax2.set_title("难度分布")

        plt.tight_layout()
        safe_name = re.sub(r"[^\w]", "_", player_name)
        filename = self.get_unique_filename(f"stabled_by_{safe_name}.png", "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.savefig(filepath, dpi=150, facecolor="white", bbox_inches="tight")
        plt.close()
        print(colorize(f"\n已生成稳定者统计图表: {filepath}", Colors.GREEN))

    setattr(cls, "do_stb_stabled_by", db_safe_operation(do_stb_stabled_by))
    setattr(cls, "_generate_stabled_by_chart", _generate_stabled_by_chart)
