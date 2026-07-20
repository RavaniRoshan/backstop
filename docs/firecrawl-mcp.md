# Firecrawl MCP — ready-to-use config

Backstop's research/competitive-benchmark workflow uses
[Firecrawl](https://firecrawl.dev) for web search + scraping. Add the block
below to your MCP client config to expose the Firecrawl tools
(`firecrawl_search`, `firecrawl_scrape`, `firecrawl_crawl`, …).

> Note: Kilo's global config schema did not accept a top-level `mcpServers`
> block at the time of writing, so this is provided as a portable reference.
> Drop it into any MCP-aware client (Cursor, Windsurf, Claude Desktop, VS Code,
> or a future Kilo release that supports `mcpServers`).

```json
{
  "mcpServers": {
    "firecrawl": {
      "url": "https://mcp.firecrawl.dev/v2/mcp",
      "headers": {
        "Authorization": "Bearer ${FIRECRAWL_API_KEY}"
      }
    }
  }
}
```

Local (stdio) alternative:

```bash
env FIRECRAWL_API_KEY="<your-key-here>" npx -y firecrawl-mcp
```

REST API (used directly for the research in
`docs/competitive-benchmark-2026-07-20.md`):

```bash
curl -s https://api.firecrawl.dev/v1/search \
  -H "Authorization: Bearer ${FIRECRAWL_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"query":"your query","limit":5}'
```

The key prefix is `fc-` (not `bfc-`); the `b` prefix returns "Unauthorized".
