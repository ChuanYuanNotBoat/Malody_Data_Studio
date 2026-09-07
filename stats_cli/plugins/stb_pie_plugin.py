import os

import matplotlib.pyplot as plt
import numpy as np


def install(cls, *, colorize, colors, db_safe_operation):
    Colors = colors

    def do_stb_pie(self, arg):
        """
        生成谱面分布饼状图（支持选择器筛选）
        """
        args = arg.split()
        mode = self.current_mode
        chart_type = "status"

        if args:
            try:
                if args[0].isdigit():
                    mode = int(args[0])
                    if len(args) > 1:
                        chart_type = args[1].lower()
                else:
                    chart_type = args[0].lower()
                    if len(args) > 1 and args[1].isdigit():
                        mode = int(args[1])
            except ValueError:
                print(colorize("错误: 模式必须是数字", Colors.RED))
                return

        cursor = self.conn.cursor()

        if chart_type == "status":
            self._generate_status_pie(cursor, mode)
        elif chart_type == "level":
            self._generate_level_pie(cursor, mode)
        else:
            print(colorize(f"错误: 不支持的图表类型 '{chart_type}'", Colors.RED))

    def _generate_status_pie(self, cursor, mode):
        where_clause, params = self.selector.build_chart_sql_where("c")

        if not self.selector.filters["modes"] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)

        where_clause += " AND c.server_exists = 1"

        cursor.execute(
            f"SELECT c.status, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.status",
            params,
        )
        status_data = cursor.fetchall()

        if not status_data:
            print(colorize("没有找到符合条件的谱面数据", Colors.YELLOW))
            return

        status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}
        labels = []
        sizes = []

        for status, count in status_data:
            labels.append(status_names.get(status, f"未知({status})"))
            sizes.append(count)

        fig, ax = plt.subplots(figsize=(10, 8))
        palette = plt.cm.Set3(np.linspace(0, 1, len(labels)))
        _, _, autotexts = ax.pie(sizes, labels=labels, autopct="%1.1f%%", colors=palette, startangle=90)

        for autotext in autotexts:
            autotext.set_color("white")
            autotext.set_fontweight("bold")

        mode_name = self.mode_names.get(mode, "未知")
        ax.set_title(
            f"谱面状态分布 - 模式 {mode} ({mode_name})\n筛选条件: {self.selector.get_current_selection()}\n(已排除已删除谱面)",
            fontsize=14,
            fontweight="bold",
        )

        base_filename = f"stb_status_pie_mode{mode}.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, facecolor="white")
        plt.close()

        print(colorize(f"\n已生成状态分布饼图: {filepath}", Colors.GREEN))

    def _generate_level_pie(self, cursor, mode):
        where_clause, params = self.selector.build_chart_sql_where("c")

        if not self.selector.filters["modes"] and self.selector.current_mode != -1:
            where_clause += " AND c.mode = ?" if where_clause != "1=1" else "c.mode = ?"
            params.append(mode)

        where_clause += " AND c.level IS NOT NULL AND c.level != '' AND CAST(c.level AS REAL) > 0 AND c.server_exists = 1"

        cursor.execute(
            f"SELECT c.level, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.level ORDER BY CAST(c.level AS REAL)",
            params,
        )
        level_data = cursor.fetchall()

        if not level_data:
            print(colorize("没有找到符合条件的难度数据", Colors.YELLOW))
            return

        level_groups = {}
        for level, count in level_data:
            try:
                level_float = float(level)
                if level_float < 5:
                    group = "1-4"
                elif level_float < 10:
                    group = "5-9"
                elif level_float < 15:
                    group = "10-14"
                else:
                    group = "15+"

                level_groups[group] = level_groups.get(group, 0) + count
            except ValueError:
                continue

        if not level_groups:
            print(colorize("没有有效的难度数据", Colors.YELLOW))
            return

        labels = list(level_groups.keys())
        sizes = list(level_groups.values())

        fig, ax = plt.subplots(figsize=(10, 8))
        palette = plt.cm.viridis(np.linspace(0, 1, len(labels)))
        _, _, autotexts = ax.pie(sizes, labels=labels, autopct="%1.1f%%", colors=palette, startangle=90)

        for autotext in autotexts:
            autotext.set_color("white")
            autotext.set_fontweight("bold")

        mode_name = self.mode_names.get(mode, "未知")
        ax.set_title(
            f"谱面难度分布 - 模式 {mode} ({mode_name})\n筛选条件: {self.selector.get_current_selection()}\n(已排除已删除谱面)",
            fontsize=14,
            fontweight="bold",
        )

        base_filename = f"stb_level_pie_mode{mode}.png"
        filename = self.get_unique_filename(base_filename, "png")
        filepath = os.path.join(self.output_dir, filename)
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, facecolor="white")
        plt.close()

        print(colorize(f"\n已生成难度分布饼图: {filepath}", Colors.GREEN))

    setattr(cls, "do_stb_pie", db_safe_operation(do_stb_pie))
    setattr(cls, "_generate_status_pie", _generate_status_pie)
    setattr(cls, "_generate_level_pie", _generate_level_pie)
