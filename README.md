# Perspective MCP

A [FastMCP](https://gofastmcp.com) server that fetches Yahoo Finance data and answers with interactive
[Perspective](https://perspective-dev.github.io/guide/index.html) charts, tables and workspaces,
plus a Streamlit chat demo driven by a Qwen model.

<img width="1902" height="799" alt="image" src="https://github.com/user-attachments/assets/985abda5-6fef-4be9-93a8-2bcd9f3617c3" />


```
Qwen ──tool call──▶ /mcp  show_prices(["^IXIC"], "ytd")
                      │  yfinance ─▶ pandas ─▶ Perspective table (in-process server)
                      ▼
         structured Visualization {url, websocket, panels, layout} + text summary for the model
                      │
browser ◀── /view/{id} <perspective-viewer> ◀──── /ws  table streamed over the Perspective websocket
```

## Quickstart

```bash
uv sync --extra demo
cp .env.example .env              # add your Qwen API key
uv run perspective-mcp            # http://localhost:8000/mcp
uv run streamlit run demo/app.py  # in a second terminal
```

Then ask *"Draw a chart of the Nasdaq year to date"*.

## Tools

| Tool             | Returns                                                                  |
|------------------|--------------------------------------------------------------------------|
| `search_symbols` | Tickers matching a company, index, ETF, currency or crypto name          |
| `show_prices`    | Line, area, bar, candlestick or OHLC chart, or a table, of price history |
| `show_quotes`    | Table of price, daily change, market cap, valuation and 52-week range    |
| `show_dashboard` | Workspace with performance and volume charts, quotes and prices tables   |

The `show_*` tools return a `Visualization` as structured content (see
[visualization.py](perspective_mcp/visualization.py)): each panel is a `<perspective-viewer>` config
bound to a table the server hosts. The text content is only the key numbers plus the link, so the
model comments on the data without it filling its context. Any client can render a visualization
by opening its `url` (add `?theme=Pro Dark` for a dark theme), or by loading `websocket` into its
own viewer and calling `restore(panel)` or `restoreWorkspace({panels, layout})`.

## Project layout

```
perspective_mcp/
  market.py         Yahoo Finance -> tidy DataFrames
  visualization.py  Panel / Visualization models and their HTML page
  viewer.html       <perspective-viewer> page, CDN version pinned to perspective-python
  server.py         MCP tools, Perspective server, /mcp /ws /view routes
demo/
  agent.py          tool-calling loop: Qwen (OpenAI-compatible API) + MCP client
  app.py            Streamlit chat
tests/              offline tests (Yahoo Finance stubbed): uv run pytest
```

To use the server from another MCP client, point it at `http://localhost:8000/mcp`
(streamable HTTP). Visualization URLs are built from the host the client used to reach the server,
so that host must also be reachable from the browser that opens them; to serve other machines run
`uv run perspective-mcp --host 0.0.0.0` and connect through the machine's hostname.
