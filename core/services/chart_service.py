# malody_api/core/services/chart_service.py
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from ...core.database import get_db_connection, db_safe_operation
from ...core.models import ChartStats, HotChart, CreatorStats
from ...utils.selector import MCSelector


class ChartService:
    """谱面数据服务"""

    @db_safe_operation
    def get_chart_stats(self, selector: MCSelector) -> ChartStats:
        """获取谱面统计信息"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_clause, params = selector.build_chart_sql_where("c")

            # 总谱面数
            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause}", params)
            total_charts = cursor.fetchone()[0] or 0

            # 唯一歌曲数
            cursor.execute(f"SELECT COUNT(DISTINCT c.sid) FROM charts c WHERE {where_clause}", params)
            unique_songs = cursor.fetchone()[0] or 0

            # 创作者数
            cursor.execute(f"SELECT COUNT(DISTINCT c.creator_name) FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL", params)
            unique_creators = cursor.fetchone()[0] or 0

            # 状态分布
            cursor.execute(f"SELECT c.status, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.status", params)
            status_results = cursor.fetchall()
            status_dist = {0: 0, 1: 0, 2: 0}
            for status, count in status_results:
                if status in [0, 1, 2]:
                    status_dist[status] = count

            # 难度分布
            cursor.execute(
                f"SELECT c.level, COUNT(*) FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' GROUP BY c.level ORDER BY CAST(c.level AS REAL)",
                params
            )
            level_results = cursor.fetchall()
            level_dist = {str(level): count for level, count in level_results}

            # 热度统计
            cursor.execute(f"SELECT AVG(c.heat), MAX(c.heat), MIN(c.heat) FROM charts c WHERE {where_clause} AND c.heat > 0", params)
            heat_stats_result = cursor.fetchone()
            heat_avg, heat_max, heat_min = heat_stats_result or (0, 0, 0)

            return ChartStats(
                total_charts=total_charts,
                unique_songs=unique_songs,
                unique_creators=unique_creators,
                status_distribution={str(k): v for k, v in status_dist.items()},
                level_distribution=level_dist,
                heat_stats={
                    "average": float(heat_avg or 0),
                    "max": float(heat_max or 0),
                    "min": float(heat_min or 0)
                }
            )

        finally:
            conn.close()

    @db_safe_operation
    def get_hot_charts(self, selector: MCSelector, sort_field: str = "heat", limit: int = 10) -> List[HotChart]:
        """获取热门谱面"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_clause, params = selector.build_chart_sql_where("c")

            valid_sort_fields = ["heat", "donate_count", "play_count", "love_count"]
            if sort_field not in valid_sort_fields:
                sort_field = "heat"

            query = f"""
            SELECT c.cid, s.title, s.artist, c.version, c.level, c.status,
                   c.creator_name, c.heat, c.donate_count
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.{sort_field} DESC
            LIMIT ?
            """
            params.append(limit)

            cursor.execute(query, params)
            results = cursor.fetchall()

            return [
                HotChart(
                    cid=row[0],
                    title=row[1],
                    artist=row[2],
                    version=row[3],
                    level=row[4],
                    status=row[5],
                    creator_name=row[6],
                    heat=row[7],
                    donate_count=row[8]
                ) for row in results
            ]

        finally:
            conn.close()

    @db_safe_operation
    def get_recent_charts(self, selector: MCSelector, days: int = 7, limit: int = 10) -> List[HotChart]:
        """获取最近更新的谱面"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            where_clause, params = selector.build_chart_sql_where("c")
            if where_clause != "1=1":
                where_clause += " AND c.last_updated >= ?"
            else:
                where_clause = "c.last_updated >= ?"
            params.append(start_date)

            query = f"""
            SELECT c.cid, s.title, s.artist, c.version, c.level, c.status,
                   c.creator_name, c.heat, c.donate_count, c.last_updated
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.last_updated DESC
            LIMIT ?
            """
            params.append(limit)

            cursor.execute(query, params)
            results = cursor.fetchall()

            return [
                HotChart(
                    cid=row[0],
                    title=row[1],
                    artist=row[2],
                    version=row[3],
                    level=row[4],
                    status=row[5],
                    creator_name=row[6],
                    heat=row[7],
                    donate_count=row[8]
                ) for row in results
            ]

        finally:
            conn.close()

    @db_safe_operation
    def get_stable_creators(self, selector: MCSelector, limit: int = 20) -> List[CreatorStats]:
        """获取Stable谱面创作者排行榜"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            temp_selector = MCSelector()
            temp_selector.current_mode = selector.current_mode
            temp_selector.set_filters(
                players=selector.filters['players'],
                difficulties=selector.filters['difficulties'],
                time_range=selector.filters['time_range'],
                modes=selector.filters['modes'],
                statuses=[2]
            )

            where_clause, params = temp_selector.build_chart_sql_where("c")

            if where_clause != "1=1":
                where_clause += " AND c.creator_name IS NOT NULL"
            else:
                where_clause = "c.creator_name IS NOT NULL"

            query = f"""
            SELECT c.creator_name, COUNT(*) as stable_count,
                AVG(CAST(c.level AS REAL)) as avg_level,
                AVG(c.heat) as avg_heat,
                MAX(c.heat) as max_heat
            FROM charts c
            WHERE {where_clause}
            GROUP BY c.creator_name
            ORDER BY stable_count DESC, avg_heat DESC
            LIMIT ?
            """
            params.append(limit)

            cursor.execute(query, params)
            results = cursor.fetchall()

            return [
                CreatorStats(
                    creator_name=row[0],
                    stable_count=row[1],
                    avg_level=float(row[2]) if row[2] else None,
                    avg_heat=float(row[3]) if row[3] else None,
                    max_heat=row[4]
                ) for row in results
            ]

        finally:
            conn.close()

    @db_safe_operation
    def get_chart_summary(self, selector: MCSelector, detail_level: str = "basic") -> Dict[str, Any]:
        """获取谱面综合统计报告"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_clause, params = selector.build_chart_sql_where("c")

            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause}", params)
            total_charts = cursor.fetchone()[0] or 0

            cursor.execute(f"SELECT COUNT(DISTINCT c.sid) FROM charts c WHERE {where_clause}", params)
            unique_songs = cursor.fetchone()[0] or 0

            cursor.execute(
                f"SELECT COUNT(DISTINCT c.creator_name) FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL",
                params
            )
            unique_creators = cursor.fetchone()[0] or 0

            cursor.execute(
                f"SELECT MIN(c.last_updated), MAX(c.last_updated) FROM charts c WHERE {where_clause} AND c.last_updated IS NOT NULL",
                params
            )
            date_range = cursor.fetchone() or (None, None)

            cursor.execute(
                f"SELECT AVG(c.heat), MAX(c.heat), MIN(c.heat) FROM charts c WHERE {where_clause} AND c.heat > 0",
                params
            )
            heat_stats_raw = cursor.fetchone() or (0, 0, 0)

            cursor.execute(
                f"SELECT AVG(CAST(c.level AS REAL)), MAX(CAST(c.level AS REAL)), MIN(CAST(c.level AS REAL)) "
                f"FROM charts c WHERE {where_clause} AND c.level IS NOT NULL AND c.level != '' AND CAST(c.level AS REAL) > 0",
                params
            )
            level_stats_raw = cursor.fetchone() or (0, 0, 0)

            cursor.execute(
                f"SELECT c.status, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.status",
                params
            )
            status_distribution = {str(row[0]): row[1] for row in cursor.fetchall()}

            summary = {
                "total_charts": total_charts,
                "unique_songs": unique_songs,
                "unique_creators": unique_creators,
                "date_range": {
                    "min_last_updated": date_range[0],
                    "max_last_updated": date_range[1]
                },
                "heat_stats": {
                    "avg": float(heat_stats_raw[0] or 0),
                    "max": float(heat_stats_raw[1] or 0),
                    "min": float(heat_stats_raw[2] or 0)
                },
                "level_stats": {
                    "avg": float(level_stats_raw[0] or 0),
                    "max": float(level_stats_raw[1] or 0),
                    "min": float(level_stats_raw[2] or 0)
                },
                "status_distribution": status_distribution
            }

            if detail_level == "detailed":
                cursor.execute(
                    f"SELECT c.creator_name, COUNT(*) as count "
                    f"FROM charts c WHERE {where_clause} AND c.creator_name IS NOT NULL "
                    f"GROUP BY c.creator_name ORDER BY count DESC LIMIT 20",
                    params
                )
                top_creators = [
                    {"creator_name": row[0], "count": row[1]}
                    for row in cursor.fetchall()
                ]
                summary["top_creators"] = top_creators

            return summary
        finally:
            conn.close()

    @db_safe_operation
    def get_chart_quality(self, selector: MCSelector) -> Dict[str, Any]:
        """检查谱面数据质量"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_clause, params = selector.build_chart_sql_where("c")

            cursor.execute(f"SELECT COUNT(*) FROM charts c WHERE {where_clause}", params)
            total = cursor.fetchone()[0] or 0

            checks = {
                "missing_creator_name": "SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.creator_name IS NULL",
                "missing_level": "SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.level IS NULL",
                "missing_last_updated": "SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.last_updated IS NULL",
                "orphan_charts_without_song": (
                    "SELECT COUNT(*) FROM charts c LEFT JOIN songs s ON c.sid = s.sid "
                    "WHERE {where_clause} AND s.sid IS NULL"
                ),
                "negative_heat": "SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.heat < 0",
                "negative_donate_count": "SELECT COUNT(*) FROM charts c WHERE {where_clause} AND c.donate_count < 0",
            }

            result = {
                "total_charts_checked": total,
                "issues": {},
                "quality_score": 100.0
            }

            total_issues = 0
            for key, query_tmpl in checks.items():
                query = query_tmpl.format(where_clause=where_clause)
                cursor.execute(query, params)
                count = cursor.fetchone()[0] or 0
                total_issues += count
                ratio = (count / total * 100) if total > 0 else 0
                result["issues"][key] = {"count": count, "ratio": round(ratio, 2)}

            if total > 0:
                score = 100 - (total_issues / total * 100)
                result["quality_score"] = round(max(score, 0), 2)

            return result
        finally:
            conn.close()

    @db_safe_operation
    def get_top_stabilizers(self, mode: int = -1, limit: int = 20) -> List[Dict[str, Any]]:
        """获取顶级稳定者排行榜"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_conditions = ["c.stabled_by_name IS NOT NULL", "c.status = 2"]
            params: List[Any] = []

            if mode != -1:
                where_conditions.append("c.mode = ?")
                params.append(mode)

            where_clause = " AND ".join(where_conditions)
            query = f"""
            SELECT
                c.stabled_by_name,
                COUNT(*) as stable_count,
                AVG(c.heat) as avg_heat,
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

            return [
                {
                    "stabilizer_name": row[0],
                    "stable_count": row[1],
                    "avg_heat": float(row[2]) if row[2] is not None else None,
                    "max_heat": float(row[3]) if row[3] is not None else None,
                    "first_stable": row[4],
                    "last_stable": row[5]
                }
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    @db_safe_operation
    def get_creator_details(
        self,
        creator_name: str,
        mode: int = -1,
        status: Optional[int] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """获取创作者详情及其谱面列表"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_conditions = ["c.creator_name LIKE ?"]
            params: List[Any] = [f"%{creator_name}%"]

            if mode != -1:
                where_conditions.append("c.mode = ?")
                params.append(mode)
            if status is not None:
                where_conditions.append("c.status = ?")
                params.append(status)

            where_clause = " AND ".join(where_conditions)

            cursor.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT c.mode), AVG(c.heat), AVG(CAST(c.level AS REAL)) "
                f"FROM charts c WHERE {where_clause}",
                params
            )
            total, modes_count, avg_heat, avg_level = cursor.fetchone() or (0, 0, 0, 0)

            cursor.execute(
                f"SELECT c.status, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.status",
                params
            )
            status_distribution = {str(row[0]): row[1] for row in cursor.fetchall()}

            cursor.execute(
                f"SELECT c.mode, COUNT(*) FROM charts c WHERE {where_clause} GROUP BY c.mode",
                params
            )
            mode_distribution = {str(row[0]): row[1] for row in cursor.fetchall()}

            list_query = f"""
            SELECT c.cid, s.title, s.artist, c.version, c.level, c.status, c.heat, c.last_updated
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.last_updated DESC
            LIMIT ?
            """
            list_params = params + [limit]
            cursor.execute(list_query, list_params)
            charts = [
                {
                    "cid": row[0],
                    "title": row[1],
                    "artist": row[2],
                    "version": row[3],
                    "level": row[4],
                    "status": row[5],
                    "heat": row[6],
                    "last_updated": row[7]
                }
                for row in cursor.fetchall()
            ]

            return {
                "creator_name": creator_name,
                "summary": {
                    "total_charts": total,
                    "mode_count": modes_count,
                    "avg_heat": float(avg_heat) if avg_heat is not None else None,
                    "avg_level": float(avg_level) if avg_level is not None else None
                },
                "status_distribution": status_distribution,
                "mode_distribution": mode_distribution,
                "charts": charts
            }
        finally:
            conn.close()

    @db_safe_operation
    def get_creator_trends(
        self,
        creator_name: str,
        period: str = "months",
        mode: int = -1,
        status: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """获取创作者谱面更新趋势"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_conditions = ["c.creator_name LIKE ?"]
            params: List[Any] = [f"%{creator_name}%"]

            if mode != -1:
                where_conditions.append("c.mode = ?")
                params.append(mode)
            if status is not None:
                where_conditions.append("c.status = ?")
                params.append(status)
            if start_date is not None:
                where_conditions.append("c.last_updated >= ?")
                params.append(start_date)
            if end_date is not None:
                where_conditions.append("c.last_updated <= ?")
                params.append(end_date)

            where_clause = " AND ".join(where_conditions)

            if period == "days":
                group_by = "DATE(c.last_updated)"
                order_by = "DATE(c.last_updated)"
            else:
                group_by = "strftime('%Y-%m', c.last_updated)"
                order_by = "strftime('%Y-%m', c.last_updated)"

            query = f"""
            SELECT {group_by}, COUNT(*)
            FROM charts c
            WHERE {where_clause}
            GROUP BY {group_by}
            ORDER BY {order_by}
            """
            cursor.execute(query, params)
            return [{"period": row[0], "count": row[1]} for row in cursor.fetchall()]
        finally:
            conn.close()

    @db_safe_operation
    def get_chart_detail(self, cid: int) -> Dict[str, Any]:
        """获取单个谱面的详细信息"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, s.title, s.artist, s.bpm, s.length, s.cover_url
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE c.cid = ?
        """, (cid,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"error": f"谱面不存在: {cid}"}
        cols = [desc[0] for desc in cursor.description]
        data = dict(zip(cols, row))
        conn.close()
        return data

    @db_safe_operation
    def get_chart_comments(
        self,
        cid: int,
        limit: int = 50,
        offset: int = 0,
        include_recommend: bool = True,
    ) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        cursor = conn.cursor()

        if include_recommend:
            cursor.execute(
                """
                SELECT tid, cid, uid, name, content, talk_type, is_recommend, talk_time, crawl_time
                FROM chart_comments
                WHERE cid = ?
                ORDER BY talk_time DESC
                LIMIT ? OFFSET ?
                """,
                (cid, limit, offset),
            )
        else:
            cursor.execute(
                """
                SELECT tid, cid, uid, name, content, talk_type, is_recommend, talk_time, crawl_time
                FROM chart_comments
                WHERE cid = ? AND is_recommend = 0
                ORDER BY talk_time DESC
                LIMIT ? OFFSET ?
                """,
                (cid, limit, offset),
            )

        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        result = [dict(zip(cols, row)) for row in rows]
        conn.close()
        return result

    @db_safe_operation
    def get_chart_recommenders(
        self,
        cid: int,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get recommender uid bindings for a chart from talk stream."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                uid,
                MAX(name) AS name,
                COUNT(*) AS recommend_records,
                MIN(talk_time) AS first_recommend_time,
                MAX(talk_time) AS last_recommend_time
            FROM chart_comments
            WHERE cid = ? AND is_recommend = 1 AND uid IS NOT NULL
            GROUP BY uid
            ORDER BY last_recommend_time DESC
            LIMIT ? OFFSET ?
            """,
            (cid, limit, offset),
        )
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        result = [dict(zip(cols, row)) for row in rows]
        conn.close()
        return result

    @db_safe_operation
    def get_stabilizer_stats(self, player_name: str) -> Dict[str, Any]:
        """获取稳定者的统计信息"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN server_exists = 1 THEN 1 ELSE 0 END) as total_excl,
                   COUNT(DISTINCT mode) as modes,
                   AVG(CASE WHEN server_exists = 1 THEN heat END) as avg_heat,
                   AVG(CASE WHEN server_exists = 1 THEN CAST(level AS REAL) END) as avg_level
            FROM charts
            WHERE stabled_by_name LIKE ? AND status = 2
        """, (f"%{player_name}%",))
        stats = cursor.fetchone()
        conn.close()
        return {
            "total": stats[0],
            "total_excluding_deleted": stats[1] or 0,
            "modes": stats[2],
            "avg_heat": float(stats[3]) if stats[3] else 0,
            "avg_level": float(stats[4]) if stats[4] else 0
        }

    @db_safe_operation
    def get_stabilizer_charts(self, player_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """获取稳定者审核的谱面列表"""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.cid, s.title, s.artist, c.version, c.level, c.mode, c.status,
                   c.heat, c.donate_count, c.play_count, c.last_updated, c.server_exists
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE c.stabled_by_name LIKE ? AND c.status = 2
            ORDER BY c.last_updated DESC
            LIMIT ?
        """, (f"%{player_name}%", limit))
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        result = [dict(zip(cols, row)) for row in rows]
        conn.close()
        return result

    @db_safe_operation
    def search_charts(self, keyword: str, selector: MCSelector, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索谱面"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_clause, params = selector.build_chart_sql_where("c")
            where_clause += " AND (s.title LIKE ? OR s.artist LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])

            query = f"""
            SELECT c.cid, s.title, s.artist, c.version, c.level, c.status,
                   c.creator_name, c.heat, c.donate_count
            FROM charts c
            JOIN songs s ON c.sid = s.sid
            WHERE {where_clause}
            ORDER BY c.heat DESC
            LIMIT ?
            """
            params.append(limit)

            cursor.execute(query, params)
            results = cursor.fetchall()

            return [
                {
                    "cid": row[0],
                    "title": row[1],
                    "artist": row[2],
                    "version": row[3],
                    "level": row[4],
                    "status": row[5],
                    "creator_name": row[6],
                    "heat": row[7],
                    "donate_count": row[8],
                    "deleted": bool(row[9])
                } for row in results
            ]

        finally:
            conn.close()

    @db_safe_operation
    def search_creators(self, keyword: str, selector: MCSelector, limit: int = 10) -> List[Dict[str, Any]]:
        """搜索创作者"""
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            where_clause, params = selector.build_chart_sql_where("c")
            where_clause += " AND c.creator_name LIKE ?"
            params.append(f"%{keyword}%")

            query = f"""
            SELECT c.creator_name, COUNT(*) as chart_count,
                   AVG(c.heat) as avg_heat, MAX(c.heat) as max_heat
            FROM charts c
            WHERE {where_clause}
            GROUP BY c.creator_name
            ORDER BY chart_count DESC
            LIMIT ?
            """
            params.append(limit)

            cursor.execute(query, params)
            results = cursor.fetchall()

            return [
                {
                    "creator_name": row[0],
                    "chart_count": row[1],
                    "avg_heat": float(row[2]) if row[2] else 0,
                    "max_heat": row[3]
                } for row in results
            ]

        finally:
            conn.close()
