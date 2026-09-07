from datetime import datetime
from typing import Any, Dict

from .chart_service import ChartService
from .crawler_task_service import crawler_task_service
from .db_maintenance_service import db_maintenance_service
from .player_service import PlayerService
from ...utils.selector import MCSelector


class DashboardService:
    def __init__(self):
        self.player_service = PlayerService()
        self.chart_service = ChartService()

    def get_overview(self) -> Dict[str, Any]:
        def as_mapping(value: Any) -> Dict[str, Any]:
            if value is None:
                return {}
            if isinstance(value, dict):
                return value
            if hasattr(value, "model_dump"):
                try:
                    return value.model_dump()
                except Exception:
                    return {}
            if hasattr(value, "dict"):
                try:
                    return value.dict()
                except Exception:
                    return {}
            return {}

        selector = MCSelector()
        selector.current_mode = 0
        mm_stats = as_mapping(self.player_service.get_mm_stats(mm_limit=200))
        chart_stats = as_mapping(self.chart_service.get_chart_stats(selector))
        db_health = db_maintenance_service.get_health()
        crawler_summary = crawler_task_service.summarize()

        return {
            "generated_at": datetime.now().isoformat(),
            "database": {
                "path": db_health.get("db_path"),
                "file_size_bytes": db_health.get("file_size_bytes"),
                "fragmentation_ratio": db_health.get("fragmentation_ratio"),
                "quick_check": db_health.get("quick_check"),
            },
            "players_mm": {
                "freshness": mm_stats.get("freshness", {}),
                "tracked_players": mm_stats.get("tracked_players", {}),
            },
            "charts": {
                "total_charts": chart_stats.get("total_charts"),
                "total_charts_excluding_deleted": chart_stats.get("total_charts_excluding_deleted", 0),
                "deleted_charts": chart_stats.get("deleted_charts", 0),
                "unique_songs": chart_stats.get("unique_songs"),
                "unique_creators": chart_stats.get("unique_creators"),
                "status_distribution": chart_stats.get("status_distribution"),
            },
            "crawler_tasks": crawler_summary,
        }


dashboard_service = DashboardService()
