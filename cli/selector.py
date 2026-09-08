import re
from datetime import datetime, timedelta
from typing import Any, Dict, List


MODE_NAMES = {
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


class MCSelector:
    """Selector helper for player/chart filtering."""

    def __init__(self):
        self.current_mode = -1
        self.filters = {
            "players": [],
            "difficulties": [],
            "time_range": None,
            "modes": [],
            "statuses": [],
        }
        self.status_names = {0: "Alpha", 1: "Beta", 2: "Stable"}

    def parse_selector(self, selector_str: str) -> Dict[str, Any]:
        if not selector_str.strip():
            return {}

        result: Dict[str, Any] = {}
        pattern = r"@([pdtsm*])\[([^\]]*)\]|@(\*)"

        for match in re.findall(pattern, selector_str):
            selector_type = match[0] or match[2]
            condition = match[1]

            if selector_type == "p":
                result["players"] = [p.strip() for p in condition.split(",") if p.strip()]
            elif selector_type == "d":
                result["difficulties"] = self._parse_difficulty_range(condition)
            elif selector_type == "t":
                result["time_range"] = self._parse_time_range(condition)
            elif selector_type == "s":
                result["statuses"] = [int(s.strip()) for s in condition.split(",") if s.strip()]
            elif selector_type == "m":
                result["modes"] = [int(m.strip()) for m in condition.split(",") if m.strip()]
            elif selector_type == "*":
                result["all"] = True

        return result

    def _parse_difficulty_range(self, condition: str) -> List[float]:
        if not condition:
            return []

        try:
            if "-" in condition:
                start, end = condition.split("-")
                return [float(start.strip()), float(end.strip())]
            return [float(condition.strip())]
        except ValueError:
            return []

    def _parse_time_range(self, condition: str) -> Dict[str, datetime]:
        now = datetime.now()
        if not condition:
            return {"start": now - timedelta(days=30), "end": now}

        try:
            if condition.endswith("d"):
                return {"start": now - timedelta(days=int(condition[:-1])), "end": now}
            if condition.endswith("h"):
                return {"start": now - timedelta(hours=int(condition[:-1])), "end": now}
            if condition.endswith("w"):
                return {"start": now - timedelta(weeks=int(condition[:-1])), "end": now}
            if condition.endswith("m"):
                return {"start": now - timedelta(days=int(condition[:-1]) * 30), "end": now}
            target_date = datetime.strptime(condition, "%Y-%m-%d")
            return {"start": target_date, "end": now}
        except (ValueError, TypeError):
            return {"start": now - timedelta(days=30), "end": now}

    def build_player_sql_where(self, base_table: str = "pr") -> tuple:
        conditions: List[str] = []
        params: List[Any] = []

        if self.filters["players"]:
            player_conditions = []
            for player in self.filters["players"]:
                if player.isdigit():
                    player_conditions.append(
                        "("
                        f"{base_table}.player_id IN (SELECT player_id FROM player_identity WHERE uid = ?)"
                        f" OR {base_table}.name IN (SELECT current_name FROM player_identity WHERE uid = ?)"
                        f" OR {base_table}.player_id IN ("
                        "SELECT pa.player_id FROM player_aliases pa "
                        "JOIN player_identity pi ON pa.player_id = pi.player_id "
                        "WHERE pi.uid = ?)"
                        ")"
                    )
                    params.extend([player, player, player])
                else:
                    player_conditions.append(
                        "("
                        f"{base_table}.name LIKE ?"
                        f" OR {base_table}.player_id IN (SELECT player_id FROM player_identity WHERE current_name LIKE ?)"
                        f" OR {base_table}.player_id IN (SELECT player_id FROM player_aliases WHERE alias LIKE ?)"
                        ")"
                    )
                    like_value = f"%{player}%"
                    params.extend([like_value, like_value, like_value])
            conditions.append(f"({' OR '.join(player_conditions)})")

        if self.filters["time_range"]:
            conditions.append(f"{base_table}.crawl_time BETWEEN ? AND ?")
            params.extend([self.filters["time_range"]["start"], self.filters["time_range"]["end"]])

        if self.filters["modes"]:
            conditions.append(f"{base_table}.mode IN ({','.join(['?'] * len(self.filters['modes']))})")
            params.extend(self.filters["modes"])
        elif self.current_mode != -1:
            conditions.append(f"{base_table}.mode = ?")
            params.append(self.current_mode)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return where_clause, params

    def build_chart_sql_where(self, base_table: str = "c") -> tuple:
        conditions: List[str] = []
        params: List[Any] = []

        if self.filters["players"]:
            creator_conditions = []
            for creator in self.filters["players"]:
                creator_conditions.append(f"{base_table}.creator_name LIKE ?")
                params.append(f"%{creator}%")
            conditions.append(f"({' OR '.join(creator_conditions)})")

        if self.filters["difficulties"]:
            if len(self.filters["difficulties"]) == 1:
                conditions.append(f"{base_table}.level = ?")
                params.append(str(self.filters["difficulties"][0]))
            elif len(self.filters["difficulties"]) == 2:
                conditions.append(f"CAST({base_table}.level AS REAL) BETWEEN ? AND ?")
                params.extend(self.filters["difficulties"])

        if self.filters["time_range"]:
            conditions.append(f"{base_table}.last_updated BETWEEN ? AND ?")
            params.extend([self.filters["time_range"]["start"], self.filters["time_range"]["end"]])

        if self.filters["modes"]:
            conditions.append(f"{base_table}.mode IN ({','.join(['?'] * len(self.filters['modes']))})")
            params.extend(self.filters["modes"])
        elif self.current_mode != -1:
            conditions.append(f"{base_table}.mode = ?")
            params.append(self.current_mode)

        if self.filters["statuses"]:
            conditions.append(f"{base_table}.status IN ({','.join(['?'] * len(self.filters['statuses']))})")
            params.extend(self.filters["statuses"])

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return where_clause, params

    def set_filters(self, **filters):
        for key, value in filters.items():
            if key in self.filters:
                self.filters[key] = value

    def clear_filters(self):
        self.filters = {
            "players": [],
            "difficulties": [],
            "time_range": None,
            "modes": [],
            "statuses": [],
        }

    def get_current_selection(self) -> str:
        parts: List[str] = []

        if self.filters["players"]:
            parts.append(f"Players: {', '.join(self.filters['players'])}")

        if self.filters["difficulties"]:
            if len(self.filters["difficulties"]) == 1:
                parts.append(f"Difficulty: {self.filters['difficulties'][0]}")
            else:
                parts.append(
                    f"Difficulty: {self.filters['difficulties'][0]}-{self.filters['difficulties'][1]}"
                )

        if self.filters["time_range"]:
            days = (self.filters["time_range"]["end"] - self.filters["time_range"]["start"]).days
            parts.append(f"Time: last {days} days")

        if self.filters["modes"]:
            mode_str = ", ".join(f"{m}({MODE_NAMES.get(m, 'Unknown')})" for m in self.filters["modes"])
            parts.append(f"Mode: {mode_str}")
        elif self.current_mode != -1:
            parts.append(f"Mode: {self.current_mode}({MODE_NAMES.get(self.current_mode, 'Unknown')})")
        else:
            parts.append("Mode: all")

        if self.filters["statuses"]:
            status_str = ", ".join(f"{s}({self.status_names.get(s, 'Unknown')})" for s in self.filters["statuses"])
            parts.append(f"Status: {status_str}")

        return " | ".join(parts) if parts else "No filters"


global_selector = MCSelector()


def deleted_sum_sql(alias: str = "c") -> str:
    """SUM expression: count of charts with server_exists=1 (not deleted)."""
    return f"SUM(CASE WHEN {alias}.server_exists = 1 THEN 1 ELSE 0 END)"


def distinct_excl_sql(alias: str, column: str) -> str:
    """DISTINCT count expression excluding deleted charts."""
    return f"COUNT(DISTINCT CASE WHEN {alias}.server_exists = 1 THEN {column} END)"


def format_dual_count(excl, incl) -> str:
    """Format as 'excl (incl)'; show only the number when equal."""
    try:
        excl = int(excl or 0)
        incl = int(incl or 0)
    except (TypeError, ValueError):
        return str(excl)
    if incl > excl:
        return f"{excl} ({incl})"
    return str(excl)
