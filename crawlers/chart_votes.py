"""Direction of legacy chart vote messages (type=1 covers both directions)."""

import re

from bs4 import BeautifulSoup


def classify_chart_vote(item):
    """Return recommend / not_recommend / None from explicit message text."""
    content = BeautifulSoup(str(item.get("content") or ""), "html.parser").get_text(" ", strip=True)
    if re.match(r"^not[\s_-]*recommend(?:ed)?\b", content, re.IGNORECASE) or content.startswith("不推荐"):
        return "not_recommend"
    if re.match(r"^recommend(?:ed)?\b", content, re.IGNORECASE) or content.startswith("推荐"):
        return "recommend"
    return None


def nonnegative_count(value):
    """Missing/invalid is unknown; an explicitly observed zero is valid."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        return int(value)
    return None
