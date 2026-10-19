"""Counters explicitly exposed by the server-rendered chart page."""

import re

from bs4 import BeautifulSoup


def parse_chart_metrics(html):
    metrics = {}
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.select(".like_area .num"):
        value_span = item.select_one("span.l")
        if value_span is None:
            continue
        raw = value_span.get_text(strip=True).replace(",", "")
        if not re.fullmatch(r"\d+", raw):
            continue
        value = int(raw)
        label = item.get_text(" ", strip=True).lower()
        icon = item.find("img")
        src = (icon.get("src", "") if icon else "").lower()
        if "donation" in label or "donate" in src or "打赏" in label:
            metrics["donate_count"] = value
        elif "hot" in label or "热度" in label:
            # The play icon labels Hot; it is not an independent play count.
            metrics["heat"] = value
        elif "play count" in label or "plays" in label or "游玩次数" in label:
            metrics["play_count"] = value
        elif "love" in src or "recommend" in label:
            metrics["love_count"] = value
            metrics["recommend_count"] = value
    return metrics
