import json
import math
import re
from datetime import date, datetime, timezone
from typing import Optional

CATEGORY_PRIORITY = {
    "ai_ml": 10,
    "product_ux": 8,
    "cycling": 8,
    "tech_startups": 7,
    "nl_news": 6,
    "science": 5,
    "climate": 5,
}

CATEGORY_CAP_WEEKDAY = 3
CATEGORY_CAP_WEEKEND = 5

CATEGORY_LABELS = {
    "ai_ml": "AI & Machine Learning",
    "product_ux": "Product & UX",
    "cycling": "Cycling",
    "tech_startups": "Tech & Startups",
    "nl_news": "Nederland",
    "science": "Wetenschap",
    "climate": "Klimaat",
}

WORDS_TO_SKIP = {"the", "a", "an", "and", "or", "in", "on", "at", "to", "of", "for", "is", "are", "was", "were"}


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())
    return {w for w in words if w not in WORDS_TO_SKIP}


def score_article(article: dict, config: dict, preferences: Optional[dict] = None) -> float:
    category = article.get("category", "")
    score = CATEGORY_PRIORITY.get(category, 3)

    # Source boost
    source_boost = float(article.get("priority_boost", 0.0) or 0.0)
    score += source_boost

    # Keyword matching from config
    cat_cfg = config.get("categories", {}).get(category, {})
    cat_keywords = set(kw.lower() for kw in cat_cfg.get("keywords", []))
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    keyword_hits = sum(1 for kw in cat_keywords if kw in text)
    score += min(keyword_hits * 0.3, 2.0)

    # Daily preference boost
    if preferences:
        interests = preferences.get("interests_today", "") or ""
        mood = preferences.get("mood", "") or ""
        pref_text = f"{interests} {mood}".lower()
        pref_words = _keywords(pref_text)
        article_words = _keywords(f"{article.get('title', '')} {article.get('summary', '')}")
        overlap = len(pref_words & article_words)
        score += overlap * 1.5

    # Recency boost
    published = article.get("published")
    if published:
        try:
            pub = datetime.fromisoformat(published)
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
            if age_hours < 6:
                score += 2.0
            elif age_hours < 12:
                score += 1.0
            elif age_hours < 24:
                score += 0.5
        except Exception:
            pass

    return score


def cluster_articles(articles: list[dict]) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    used = set()

    for i, a in enumerate(articles):
        if i in used:
            continue
        cluster = [a]
        words_a = _keywords(a.get("title", ""))
        for j, b in enumerate(articles):
            if j <= i or j in used:
                continue
            words_b = _keywords(b.get("title", ""))
            if len(words_a & words_b) >= 3:
                cluster.append(b)
                used.add(j)
        used.add(i)
        clusters.append(cluster)

    return clusters


def _reading_time(text: str) -> int:
    words = len(text.split())
    return max(1, math.ceil(words / 200))


def curate(
    articles: list[dict],
    config: dict,
    preferences: Optional[dict] = None,
    max_articles: int = 15,
    weekend_mode: bool = False,
) -> list[dict]:
    cap = CATEGORY_CAP_WEEKEND if weekend_mode else CATEGORY_CAP_WEEKDAY

    # Score all
    for a in articles:
        a["_score"] = score_article(a, config, preferences)

    # Sort by score descending
    articles = sorted(articles, key=lambda a: a["_score"], reverse=True)

    # Cluster and pick best per cluster
    clusters = cluster_articles(articles)
    representatives: list[dict] = []
    for cluster in clusters:
        best = max(cluster, key=lambda a: a["_score"])
        best["_related"] = [c["source_name"] for c in cluster if c is not best]
        representatives.append(best)

    # Re-sort representatives
    representatives = sorted(representatives, key=lambda a: a["_score"], reverse=True)

    # Cap per category
    category_counts: dict[str, int] = {}
    selected: list[dict] = []
    for a in representatives:
        cat = a.get("category", "")
        if category_counts.get(cat, 0) >= cap:
            continue
        category_counts[cat] = category_counts.get(cat, 0) + 1
        selected.append(a)
        if len(selected) >= max_articles:
            break

    return selected


def format_krant_markdown(articles: list[dict], edition_date: Optional[str] = None) -> str:
    if edition_date is None:
        edition_date = date.today().isoformat()

    # Group by category
    by_cat: dict[str, list[dict]] = {}
    for a in articles:
        cat = a.get("category", "other")
        by_cat.setdefault(cat, []).append(a)

    lines = [
        f"# De Lippershey Krant — {edition_date}",
        "",
        f"*{len(articles)} articles selected*",
        "",
    ]

    for cat, label in CATEGORY_LABELS.items():
        cat_articles = by_cat.get(cat, [])
        if not cat_articles:
            continue
        lines.append(f"## {label}")
        lines.append("")
        for a in cat_articles:
            title = a.get("title", "No title")
            link = a.get("link", "")
            source = a.get("source_name", "")
            summary = a.get("summary", "")
            related = a.get("_related", [])

            rt = _reading_time(summary) if summary else 1
            lines.append(f"### [{title}]({link})")
            lines.append(f"*{source} · ~{rt} min read*")
            if summary:
                lines.append("")
                lines.append(summary[:300] + ("..." if len(summary) > 300 else ""))
            if related:
                lines.append("")
                lines.append(f"*Also covered by: {', '.join(related)}*")
            lines.append("")

    return "\n".join(lines)


def format_krant_json(articles: list[dict], edition_date: Optional[str] = None) -> str:
    if edition_date is None:
        edition_date = date.today().isoformat()

    by_cat: dict[str, list[dict]] = {}
    for a in articles:
        cat = a.get("category", "other")
        by_cat.setdefault(cat, []).append(a)

    sections = []
    for cat, label in CATEGORY_LABELS.items():
        cat_articles = by_cat.get(cat, [])
        if not cat_articles:
            continue
        sections.append({
            "category": cat,
            "label": label,
            "articles": [
                {
                    "title": a.get("title", ""),
                    "link": a.get("link", ""),
                    "source": a.get("source_name", ""),
                    "summary": a.get("summary", "")[:300],
                    "published": a.get("published", ""),
                    "score": round(a.get("_score", 0), 2),
                    "related_sources": a.get("_related", []),
                }
                for a in cat_articles
            ],
        })

    output = {
        "date": edition_date,
        "article_count": len(articles),
        "sections": sections,
    }
    return json.dumps(output, ensure_ascii=False, indent=2)
