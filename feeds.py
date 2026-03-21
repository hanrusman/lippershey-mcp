import asyncio
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp
import feedparser

import storage

TIMEOUT = aiohttp.ClientTimeout(total=15)
MAX_ENTRIES_PER_FEED = 50


def _strip_html(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _parse_date(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


async def fetch_single_feed(session: aiohttp.ClientSession, source: dict) -> list[dict]:
    url = source["url"]
    try:
        async with session.get(url, timeout=TIMEOUT) as resp:
            content = await resp.read()
        parsed = feedparser.parse(content)
        entries = parsed.entries[:MAX_ENTRIES_PER_FEED]
        articles = []
        for entry in entries:
            pub_dt = _parse_date(entry)
            published = pub_dt.isoformat() if pub_dt else None
            summary = _strip_html(
                getattr(entry, "summary", "") or getattr(entry, "description", "")
            )
            articles.append({
                "url": url,
                "title": getattr(entry, "title", "").strip(),
                "link": getattr(entry, "link", ""),
                "summary": summary[:500],
                "published": published,
                "source_name": source["name"],
                "category": source["category"],
            })
        return articles
    except Exception as exc:
        print(f"[feeds] Failed to fetch {url}: {exc}")
        return []


async def fetch_all_feeds(sources: list[dict]) -> list[dict]:
    async with aiohttp.ClientSession(headers={"User-Agent": "Lippershey-MCP/1.0"}) as session:
        tasks = [fetch_single_feed(session, src) for src in sources]
        results = await asyncio.gather(*tasks, return_exceptions=False)
    all_articles = [article for batch in results for article in batch]
    return all_articles


def filter_by_hours(articles: list[dict], hours: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    filtered = []
    for a in articles:
        if not a.get("published"):
            filtered.append(a)  # keep if no date info
            continue
        try:
            pub = datetime.fromisoformat(a["published"])
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            if pub >= cutoff:
                filtered.append(a)
        except Exception:
            filtered.append(a)
    return filtered


async def fetch_and_cache(sources: list[dict], hours: int = 24) -> list[dict]:
    all_articles = await fetch_all_feeds(sources)
    recent = filter_by_hours(all_articles, hours)
    if recent:
        await storage.cache_articles(recent)
    return recent
