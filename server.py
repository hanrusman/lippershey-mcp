import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import yaml
from mcp.server.fastmcp import FastMCP

import storage
import feeds as feeds_module
import curator

CONFIG_PATH = os.environ.get("LIPPERSHEY_CONFIG", "/app/config.yaml")

# Load config
with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)


@asynccontextmanager
async def lifespan(server: FastMCP):
    await storage.init_db()
    await storage.seed_sources_from_config(CONFIG.get("feeds", []))
    yield


app = FastMCP("lippershey", lifespan=lifespan)


@app.tool()
async def lippershey_get_krant(date_str: str = "", format: str = "markdown") -> str:
    """Get today's krant (newspaper digest) or a specific past edition.

    Args:
        date_str: ISO date string like '2024-01-15'. Defaults to today.
        format: 'markdown' or 'json'.
    """
    target = date_str.strip() if date_str.strip() else date.today().isoformat()
    krant = await storage.get_krant(target)
    if not krant:
        return f"No krant found for {target}. Run lippershey_curate to generate one."
    if format == "json":
        return krant.get("content_json", "{}")
    return krant.get("content_md", "")


@app.tool()
async def lippershey_update_preferences(
    interests_today: str = "",
    mood: str = "",
    time_budget: int = 20,
) -> str:
    """Store today's reading preferences to personalise curation.

    Args:
        interests_today: Topics you're particularly interested in today (free text).
        mood: e.g. 'focused', 'curious', 'light reading'.
        time_budget: Minutes available for reading today.
    """
    today = date.today().isoformat()
    await storage.save_preferences(today, interests_today, mood, time_budget)
    return f"Preferences saved for {today}: interests='{interests_today}', mood='{mood}', time_budget={time_budget}min"


@app.tool()
async def lippershey_fetch_feeds(
    categories: str = "",
    hours: int = 24,
) -> str:
    """Fetch RSS feeds and cache fresh articles.

    Args:
        categories: Comma-separated list of categories to filter (leave empty for all).
        hours: How many hours back to consider articles as 'recent'.
    """
    all_sources = await storage.get_sources(active_only=True)
    cat_list = [c.strip() for c in categories.split(",") if c.strip()] if categories else []
    if cat_list:
        sources = [s for s in all_sources if s["category"] in cat_list]
    else:
        sources = all_sources

    if not sources:
        return "No active sources found."

    articles = await feeds_module.fetch_and_cache(sources, hours=hours)

    by_cat: dict[str, int] = {}
    for a in articles:
        cat = a.get("category", "unknown")
        by_cat[cat] = by_cat.get(cat, 0) + 1

    summary_lines = [f"Fetched {len(articles)} articles from {len(sources)} feeds:"]
    for cat, count in sorted(by_cat.items()):
        summary_lines.append(f"  • {cat}: {count}")
    return "\n".join(summary_lines)


@app.tool()
async def lippershey_curate(
    max_articles: int = 0,
    weekend_mode: bool = False,
) -> str:
    """Score, cluster, select and save today's krant edition.

    Args:
        max_articles: Override max articles (0 = use config default).
        weekend_mode: Use weekend settings (more articles, longer lookback).
    """
    today = date.today()
    is_weekend = today.weekday() >= 5 or weekend_mode

    prefs_cfg = CONFIG.get("default_preferences", {})
    mode_cfg = prefs_cfg.get("weekend" if is_weekend else "weekday", {})

    if max_articles <= 0:
        max_articles = mode_cfg.get("max_articles", 15)
    lookback_hours = mode_cfg.get("lookback_hours", 24)

    preferences = await storage.get_preferences(today.isoformat())
    articles = await storage.get_cached_articles(hours=lookback_hours)

    if not articles:
        return "No cached articles found. Run lippershey_fetch_feeds first."

    # Attach source boost from sources table
    sources_map = {s["url"]: s for s in await storage.get_sources()}
    for a in articles:
        src = sources_map.get(a.get("url", ""))
        if src:
            a["priority_boost"] = src.get("priority_boost", 0.0)

    selected = curator.curate(
        articles,
        CONFIG,
        preferences=preferences,
        max_articles=max_articles,
        weekend_mode=is_weekend,
    )

    date_str = today.isoformat()
    content_md = curator.format_krant_markdown(selected, edition_date=date_str)
    content_json = curator.format_krant_json(selected, edition_date=date_str)

    await storage.save_krant(date_str, content_md, content_json, len(selected))

    return f"Krant generated for {date_str} with {len(selected)} articles.\n\n{content_md}"


@app.tool()
async def lippershey_get_archive(days: int = 7) -> str:
    """List past krant editions.

    Args:
        days: How many days back to look (default 7).
    """
    editions = await storage.get_archive(days)
    if not editions:
        return f"No editions found in the past {days} days."
    lines = [f"Archive — last {days} days:"]
    for e in editions:
        lines.append(f"  • {e['date']}: {e['article_count']} articles")
    return "\n".join(lines)


@app.tool()
async def lippershey_get_sources() -> str:
    """List all configured RSS feed sources."""
    sources = await storage.get_sources(active_only=False)
    if not sources:
        return "No sources configured."
    by_cat: dict[str, list[dict]] = {}
    for s in sources:
        by_cat.setdefault(s["category"], []).append(s)
    lines = [f"Sources ({len(sources)} total):"]
    for cat, srcs in sorted(by_cat.items()):
        lines.append(f"\n**{cat}**")
        for s in srcs:
            boost = f" [+{s['priority_boost']}]" if s.get("priority_boost") else ""
            active = "" if s["active"] else " [inactive]"
            lines.append(f"  • {s['name']}{boost}{active}")
            lines.append(f"    {s['url']}")
    return "\n".join(lines)


@app.tool()
async def lippershey_add_source(
    url: str,
    name: str,
    category: str,
    priority_boost: float = 0.0,
) -> str:
    """Add a new RSS feed source.

    Args:
        url: Feed URL.
        name: Human-readable name for the source.
        category: One of: ai_ml, product_ux, cycling, tech_startups, nl_news, science, climate.
        priority_boost: Extra score boost for articles from this source (0.0–2.0).
    """
    valid_cats = {"ai_ml", "product_ux", "cycling", "tech_startups", "nl_news", "science", "climate"}
    if category not in valid_cats:
        return f"Invalid category '{category}'. Valid: {', '.join(sorted(valid_cats))}"
    await storage.add_source(url, name, category, priority_boost)
    return f"Source added: {name} ({category}) → {url}"


if __name__ == "__main__":
    app.run(transport="sse")
