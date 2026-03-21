# Lippershey MCP

A personal newspaper MCP server. Fetches RSS feeds, scores and clusters articles by your daily interests, and delivers a curated digest — the *krant* — via Claude.

## Quick start

```bash
docker compose up -d
```

The server listens on port **8420**.

## Claude MCP configuration

Add to your `~/.claude/claude_desktop_config.json` (or Claude Code MCP settings):

```json
{
  "mcpServers": {
    "lippershey": {
      "type": "http",
      "url": "http://optiplex:8420/mcp"
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `lippershey_fetch_feeds` | Fetch RSS feeds and cache articles. Optionally filter by category and lookback window. |
| `lippershey_update_preferences` | Tell the krant what you're into today: interests, mood, available reading time. |
| `lippershey_curate` | Score, cluster and select the best articles. Saves today's edition. |
| `lippershey_get_krant` | Retrieve today's (or any past) edition as Markdown or JSON. |
| `lippershey_get_archive` | List past editions and article counts. |
| `lippershey_get_sources` | Show all configured RSS sources grouped by category. |
| `lippershey_add_source` | Add a new RSS feed to a category. |

## Daily workflow

A typical morning session in Claude:

1. **Update preferences** — "I'm interested in AI agents and product strategy today, mood is focused, 20 minutes to read."
   → calls `lippershey_update_preferences`

2. **Fetch feeds** — "Fetch today's feeds."
   → calls `lippershey_fetch_feeds`

3. **Curate** — "Curate today's krant."
   → calls `lippershey_curate` — scores articles, clusters duplicates, applies preference boosts, saves the edition

4. **Read** — "Show me today's krant."
   → calls `lippershey_get_krant`

## Categories

| Category | Priority | Description |
|----------|----------|-------------|
| `ai_ml` | 10 | AI, LLMs, machine learning |
| `product_ux` | 8 | Product management, UX, discovery |
| `cycling` | 8 | Road cycling, races, gear |
| `tech_startups` | 7 | Tech industry, software engineering |
| `nl_news` | 6 | Dutch tech & news |
| `science` | 5 | Science & research |
| `climate` | 5 | Climate, energy transition |

## Configuration

Edit `config.yaml` to add feeds, adjust priorities, or change keyword lists. The file is mounted read-only into the container; restart after changes.

## Data

SQLite database is stored in a named Docker volume (`lippershey-data`) at `/data/lippershey.db`. Tables:

- `preferences` — daily reading preferences
- `feed_cache` — fetched articles (indexed by fetch time and category)
- `krant_archive` — past editions (Markdown + JSON)
- `sources` — feed sources with boost values
