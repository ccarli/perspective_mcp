"""Perspective MCP server: Yahoo Finance data as Perspective charts, tables and workspaces.

One process serves three endpoints:
  /mcp        the MCP tools (streamable HTTP)
  /ws         the Perspective websocket hosting every table the tools load
  /view/{id}  a standalone page rendering a tool's visualization
"""

import argparse
import contextlib
import uuid
from typing import Annotated, Literal

import pandas as pd
import perspective
import pyarrow as pa
import uvicorn
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from fastmcp.tools import ToolResult
from perspective.handlers.starlette import PerspectiveStarletteHandler
from pydantic import AfterValidator, Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, Response
from starlette.websockets import WebSocket, WebSocketDisconnect

from perspective_mcp import market
from perspective_mcp.market import PRICE_COLUMNS, Interval, Period
from perspective_mcp.visualization import Layout, Panel, Plugin, Visualization, kind_of, split, tabs

DEFAULT_URL = "http://localhost:8000"
OUTPUT_SCHEMA = Visualization.model_json_schema()

Style = Literal["line", "area", "bar", "candlestick", "ohlc", "table"]
STYLES: dict[Style, Plugin] = {
    "line": "Y Line",
    "area": "Y Area",
    "bar": "Y Bar",
    "candlestick": "Candlestick",
    "ohlc": "OHLC",
    "table": "Datagrid",
}


def clean_symbols(symbols: list[str]) -> list[str]:
    return sorted({symbol.strip().upper() for symbol in symbols})


Symbols = Annotated[
    list[str],
    Field(min_length=1, max_length=10, description="Yahoo Finance tickers, e.g. ['^IXIC'] or ['AAPL', 'MSFT']"),
    AfterValidator(clean_symbols),
]

mcp = FastMCP(
    "perspective-finance",
    instructions=(
        "Fetches Yahoo Finance data and shows it to the user as interactive Perspective visualizations. "
        "Common indices: Nasdaq Composite ^IXIC, Nasdaq 100 ^NDX, S&P 500 ^GSPC, Dow Jones ^DJI, "
        "Russell 2000 ^RUT, VIX ^VIX. Use search_symbols for any other name."
    ),
)
engine = perspective.Server()
client = engine.new_local_client()
visualizations: dict[str, Visualization] = {}


def arrow_bytes(frame: pd.DataFrame) -> bytes:
    """Arrow IPC stream: unlike a DataFrame, Perspective takes it without adding an `index` column."""
    table = pa.Table.from_pandas(frame, preserve_index=False)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def host(name: str, frame: pd.DataFrame) -> str:
    if name in client.get_hosted_table_names():
        client.open_table(name).replace(arrow_bytes(frame))
    else:
        client.table(arrow_bytes(frame), name=name)
    return name


def load_prices(symbols: list[str], period: Period, interval: Interval) -> tuple[str, pd.DataFrame]:
    prices = market.history(symbols, period, interval)
    return host(f"history/{'+'.join(symbols)}/{period}/{interval}", prices), prices


def load_quotes(symbols: list[str]) -> tuple[str, pd.DataFrame]:
    quotes = market.quotes(symbols)
    return host(f"quotes/{'+'.join(symbols)}", quotes), quotes


def summarize(prices: pd.DataFrame, symbols: list[str]) -> str:
    lines = []
    for symbol, rows in prices.groupby("Symbol"):
        first, last = rows.iloc[0], rows.iloc[-1]
        lines.append(
            f"{symbol}: {first['Close']:,.2f} on {first['Date']} -> {last['Close']:,.2f} on {last['Date']} "
            f"({last['Change %']:+.2f}%), period low {rows['Low'].min():,.2f}, high {rows['High'].max():,.2f}"
        )
    if missing := sorted(set(symbols) - set(prices["Symbol"])):
        lines.append(f"No data for {', '.join(missing)}")
    return "\n".join(lines)


def price_chart(table: str, title: str, plugin: Plugin, columns: list[str]) -> Panel:
    return Panel(table=table, title=title, plugin=plugin, columns=columns, group_by=["Date"], split_by=["Symbol"])


def price_grid(table: str, title: str) -> Panel:
    return Panel(
        table=table,
        title=title,
        columns=PRICE_COLUMNS,
        sort=[("Date", "desc")],
        columns_config={"Change %": {"fg_mode": "color"}},
    )


def quote_grid(table: str) -> Panel:
    return Panel(table=table, title="Quotes", columns_config={"Day %": {"fg_mode": "color"}})


def base_url() -> str:
    with contextlib.suppress(RuntimeError):
        return str(get_http_request().base_url).rstrip("/")
    return DEFAULT_URL


def publish(panels: dict[str, Panel], summary: str, layout: Layout | None = None) -> ToolResult:
    view_id = uuid.uuid4().hex[:12]
    url = base_url()
    visualization = Visualization(
        id=view_id,
        kind=kind_of(panels, layout),
        url=f"{url}/view/{view_id}",
        websocket=f"{url.replace('http', 'ws', 1)}/ws",
        panels=panels,
        layout=layout,
        summary=summary,
    )
    visualizations[view_id] = visualization
    return ToolResult(
        content=f"{summary}\n\nShown to the user as an interactive {visualization.kind}: {visualization.url}",
        structured_content=visualization,
    )


@mcp.tool
def search_symbols(query: str) -> list[market.SymbolMatch]:
    """Find Yahoo Finance tickers for a company, index, ETF, currency or crypto name."""
    return market.search(query)


@mcp.tool(output_schema=OUTPUT_SCHEMA)
def show_prices(
    symbols: Symbols, period: Period = "ytd", interval: Interval = "1d", style: Style = "line"
) -> ToolResult:
    """Show historical prices as a chart or a table. Several symbols are charted by % change to compare them."""
    table, prices = load_prices(symbols, period, interval)
    title = f"{', '.join(symbols)} · {period}"
    if style == "table":
        panel = price_grid(table, title)
    elif style in ("candlestick", "ohlc"):
        panel = price_chart(table, title, STYLES[style], ["Open", "Close", "High", "Low"])
    else:
        panel = price_chart(table, title, STYLES[style], ["Change %" if len(symbols) > 1 else "Close"])
    return publish({"prices": panel}, summarize(prices, symbols))


@mcp.tool(output_schema=OUTPUT_SCHEMA)
def show_quotes(symbols: Symbols) -> ToolResult:
    """Show a table of current price, daily change, market cap, valuation ratios and 52-week range."""
    table, quotes = load_quotes(symbols)
    return publish({"quotes": quote_grid(table)}, quotes.to_csv(index=False, float_format="%.2f"))


@mcp.tool(output_schema=OUTPUT_SCHEMA)
def show_dashboard(symbols: Symbols, period: Period = "ytd") -> ToolResult:
    """Show a workspace with performance and volume charts above quote and price tables."""
    history_table, prices = load_prices(symbols, period, "1d")
    quotes_table, _ = load_quotes(symbols)
    panels = {
        "performance": price_chart(history_table, "Performance %", "Y Line", ["Change %"]),
        "volume": price_chart(history_table, "Volume", "Y Bar", ["Volume"]),
        "quotes": quote_grid(quotes_table),
        "prices": price_grid(history_table, "Prices"),
    }
    layout = split(
        split(tabs("performance"), tabs("volume"), orientation="horizontal", sizes=[0.6, 0.4]),
        tabs("quotes", "prices"),
        orientation="vertical",
        sizes=[0.6, 0.4],
    )
    return publish(panels, summarize(prices, symbols), layout)


@mcp.custom_route("/view/{view_id}", methods=["GET"])
async def view_page(request: Request) -> Response:
    if visualization := visualizations.get(request.path_params["view_id"]):
        return HTMLResponse(visualization.to_html())
    return PlainTextResponse("Unknown view: the server may have restarted.", status_code=404)


async def perspective_websocket(websocket: WebSocket) -> None:
    with contextlib.suppress(WebSocketDisconnect):
        await PerspectiveStarletteHandler(perspective_server=engine, websocket=websocket).run()


app = mcp.http_app(path="/mcp")
app.router.add_websocket_route("/ws", perspective_websocket)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Perspective MCP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
