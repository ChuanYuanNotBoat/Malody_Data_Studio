import copy
from datetime import datetime, timedelta

from selector import format_dual_count


def install(cls, *, colorize, colors, db_safe_operation, get_separator):
    Colors = colors

    def _parse_dt(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        return None

    def do_search(self, arg):
        """search <keyword> [player|chart|creator] [mode]"""
        args = arg.split()
        if not args:
            print(colorize("错误: 请输入搜索关键词", Colors.RED))
            return

        keyword = args[0]
        search_type = "player"
        mode = self.current_mode

        if len(args) > 1:
            search_type = args[1].lower()

        if len(args) > 2:
            try:
                mode = int(args[2])
            except ValueError:
                print(colorize("错误: 模式必须是数字", Colors.RED))
                return

        cursor = self.conn.cursor()

        if search_type == "player":
            self._search_players(cursor, keyword, mode)
        elif search_type == "chart":
            self._search_charts(cursor, keyword, mode)
        elif search_type == "creator":
            self._search_creators(cursor, keyword, mode)
        else:
            print(colorize(f"错误: 不支持的搜索类型 '{search_type}'", Colors.RED))

    def _build_player_where(self, mode):
        selector = copy.deepcopy(self.selector)
        if not selector.filters["modes"] and mode != -1:
            selector.current_mode = mode
        return selector.build_player_sql_where("pr")

    def _build_chart_where(self, mode):
        selector = copy.deepcopy(self.selector)
        if not selector.filters["modes"] and mode != -1:
            selector.current_mode = mode
        return selector.build_chart_sql_where("c")

    def _search_players(self, cursor, keyword, mode):
        where_clause, params = self._build_player_where(mode)

        # UID direct lookup path
        if keyword.isdigit():
            cursor.execute(
                "SELECT pi.player_id, pi.current_name, pi.uid FROM player_identity pi WHERE pi.uid = ?",
                (keyword,),
            )
            result = cursor.fetchone()
            if result:
                player_id, name, uid = result
                player_where, player_params = self._build_player_where(mode)
                player_where += " AND pr.player_id = ?"
                player_params.append(player_id)

                cursor.execute(
                    f"""
                    SELECT pr.rank, pr.lv, pr.acc, pr.combo, pr.pc, pr.crawl_time
                    FROM player_rankings pr
                    WHERE {player_where}
                    ORDER BY pr.crawl_time DESC
                    LIMIT 1
                    """,
                    player_params,
                )
                player_data = cursor.fetchone()
                if player_data:
                    rank, lv, acc, combo, pc, _crawl_time = player_data
                    print(colorize(f"\n玩家: {name} (UID: {uid})", Colors.CYAN))
                    print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
                    print(get_separator())
                    print(f"排名: {rank}, 等级: {lv}, 准确率: {acc:.2f}%")
                    print(f"连击: {combo}, 游玩次数: {pc}")
                    return

            print(colorize(f"未找到 UID={keyword} 的玩家", Colors.YELLOW))
            return

        cursor.execute("SELECT MAX(pr.crawl_time) FROM player_rankings pr WHERE " + where_clause, params)
        latest_time = cursor.fetchone()[0]
        if not latest_time:
            print(colorize(f"未找到包含 '{keyword}' 的玩家", Colors.YELLOW))
            return

        end_time = _parse_dt(latest_time)
        like_value = f"%{keyword}%"

        def _query_window(start_time, end_time_obj):
            query = f"""
            WITH latest AS (
                SELECT pr.player_id, pr.mode, MAX(pr.crawl_time) AS max_time
                FROM player_rankings pr
                WHERE {where_clause}
                  AND pr.crawl_time BETWEEN ? AND ?
                GROUP BY pr.player_id, pr.mode
            )
            SELECT pr.name, pr.rank, pr.lv, pr.acc, pr.crawl_time, pr.player_id, pr.mode
            FROM player_rankings pr
            JOIN latest l
              ON l.player_id = pr.player_id
             AND l.mode = pr.mode
             AND l.max_time = pr.crawl_time
            WHERE {where_clause}
              AND (
                pr.name LIKE ?
                OR EXISTS (SELECT 1 FROM player_aliases pa WHERE pa.player_id = pr.player_id AND pa.alias LIKE ?)
                OR EXISTS (SELECT 1 FROM player_identity pi WHERE pi.player_id = pr.player_id AND pi.current_name LIKE ?)
              )
            ORDER BY pr.rank ASC, pr.crawl_time DESC
            LIMIT 10
            """
            qparams = params + [start_time, end_time_obj] + params + [like_value, like_value, like_value]
            cursor.execute(query, qparams)
            return cursor.fetchall()

        if self.selector.filters.get("time_range"):
            start_time = self.selector.filters["time_range"].get("start")
            if isinstance(start_time, str):
                start_time = _parse_dt(start_time)
            results = _query_window(start_time, end_time)
        else:
            results = []
            for hours in (24, 72, 168, 720):
                candidate = _query_window(end_time - timedelta(hours=hours), end_time)
                results = candidate
                if len(candidate) >= 10:
                    break

        if results:
            print(colorize(f"\n找到 {len(results)} 个匹配玩家", Colors.CYAN))
            print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
            print(get_separator())
            for name, rank, lv, acc, _crawl_time, _player_id, _mode in results:
                print(f"{name}: 排名 {rank}, 等级 {lv}, 准确率 {acc:.2f}%")
        else:
            print(colorize(f"未找到包含 '{keyword}' 的玩家", Colors.YELLOW))

    def _search_charts(self, cursor, keyword, mode):
        where_clause, params = self._build_chart_where(mode)
        where_clause += " AND (s.title LIKE ? OR s.artist LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])

        cursor.execute(
            f"""
            SELECT c.cid, c.version, c.level, c.status, s.title, s.artist,
                c.creator_name, c.heat, c.donate_count, c.last_updated, c.server_exists
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.heat DESC LIMIT 10
            """,
            params,
        )
        results = cursor.fetchall()
        if results:
            print(colorize(f"\n找到 {len(results)} 个匹配谱面", Colors.CYAN))
            print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
            print(get_separator())
            print(colorize("(* 前缀表示已从服务器删除的谱面)", Colors.YELLOW))
            for cid, version, level, status, title, artist, creator, heat, donate, updated, server_exists in results:
                status_name = {0: "Alpha", 1: "Beta", 2: "Stable"}.get(status, "Unknown")
                if not server_exists:
                    title = "*" + title
                print(f"  {title} - {artist} (Lv.{level})")
                print(f"    版本: {version}, 状态: {status_name}, 热度: {heat}")
                print(f"    创作者: {creator}, CID: {cid}")
        else:
            print(colorize(f"未找到包含 '{keyword}' 的谱面", Colors.YELLOW))

    def _search_creators(self, cursor, keyword, mode):
        where_clause, params = self._build_chart_where(mode)
        where_clause += " AND c.creator_name LIKE ?"
        params.append(f"%{keyword}%")

        cursor.execute(
            f"""
            SELECT c.creator_name, COUNT(*) as chart_count,
                SUM(CASE WHEN c.server_exists = 1 THEN 1 ELSE 0 END) as chart_count_excl,
                AVG(CASE WHEN c.server_exists = 1 THEN c.heat END) as avg_heat,
                MAX(c.heat) as max_heat
            FROM charts c
            WHERE {where_clause}
            GROUP BY c.creator_name
            ORDER BY chart_count DESC LIMIT 10
            """,
            params,
        )
        results = cursor.fetchall()
        if results:
            print(colorize(f"\n找到 {len(results)} 个匹配创作者", Colors.CYAN))
            print(colorize(f"筛选条件: {self.selector.get_current_selection()}", Colors.YELLOW))
            print(get_separator())
            for creator, count, count_excl, avg_heat, max_heat in results:
                print(f"  {creator}: {format_dual_count(count_excl, count)} 个谱面")
                print(f"    平均热度: {avg_heat:.1f}, 最高热度: {max_heat}")
        else:
            print(colorize(f"未找到包含 '{keyword}' 的创作者", Colors.YELLOW))

    setattr(cls, "do_search", db_safe_operation(do_search))
    setattr(cls, "_search_players", _search_players)
    setattr(cls, "_search_charts", _search_charts)
    setattr(cls, "_search_creators", _search_creators)
    setattr(cls, "_build_player_where", _build_player_where)
    setattr(cls, "_build_chart_where", _build_chart_where)
