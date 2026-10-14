from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastmcp import Client
from httpx import ASGITransport, AsyncClient

from perspective_mcp import market, server
from perspective_mcp.visualization import Visualization


def fake_download(symbols: list[str], **_) -> pd.DataFrame:
    columns = pd.MultiIndex.from_product(
        [["Close", "High", "Low", "Open", "Volume"], symbols], names=["Price", "Ticker"]
    )
    prices = np.outer([100.0, 200.0, 300.0], np.ones(len(columns)))
    return pd.DataFrame(prices, index=pd.date_range("2026-01-02", periods=3, name="Date"), columns=columns)


def fake_ticker(symbol: str) -> SimpleNamespace:
    return SimpleNamespace(info={"shortName": symbol, "regularMarketPrice": 10.0, "regularMarketChangePercent": -1.5})


def fake_search(query: str, max_results: int) -> SimpleNamespace:
    return SimpleNamespace(quotes=[{"symbol": "^IXIC", "shortname": "NASDAQ Composite", "quoteType": "INDEX"}])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(market.yf, "download", fake_download)
    monkeypatch.setattr(market.yf, "Ticker", fake_ticker)
    monkeypatch.setattr(market.yf, "Search", fake_search)


@pytest.fixture
async def mcp_client():
    async with Client(server.mcp) as client:
        yield client


async def test_tools(mcp_client):
    tools = {tool.name for tool in await mcp_client.list_tools()}
    assert tools == {"search_symbols", "show_prices", "show_quotes", "show_dashboard"}


async def test_search_symbols(mcp_client):
    result = await mcp_client.call_tool("search_symbols", {"query": "nasdaq"})
    assert result.structured_content["result"][0]["symbol"] == "^IXIC"


@pytest.mark.parametrize(
    ("style", "kind", "plugin"),
    [("line", "chart", "Y Line"), ("candlestick", "chart", "Candlestick"), ("table", "table", "Datagrid")],
)
async def test_show_prices(mcp_client, style, kind, plugin):
    result = await mcp_client.call_tool("show_prices", {"symbols": ["^ixic"], "style": style})
    visualization = Visualization.model_validate(result.structured_content)
    panel = visualization.panels["prices"]
    assert (visualization.kind, panel.plugin) == (kind, plugin)
    assert panel.table in server.client.get_hosted_table_names()
    assert result.content[0].text.startswith("^IXIC: 100.00 on 2026-01-02 -> 300.00 on 2026-01-04 (+200.00%)")


async def test_several_symbols_are_compared_by_change(mcp_client):
    result = await mcp_client.call_tool("show_prices", {"symbols": ["MSFT", "AAPL"]})
    assert result.structured_content["panels"]["prices"]["columns"] == ["Change %"]
    assert result.structured_content["panels"]["prices"]["title"].startswith("AAPL, MSFT")


async def test_show_quotes(mcp_client):
    result = await mcp_client.call_tool("show_quotes", {"symbols": ["AAPL"]})
    assert result.structured_content["kind"] == "table"
    assert result.content[0].text.startswith("Symbol,Name,Type,Currency,Price,Day %")
    assert "AAPL,AAPL,,,10.00,-1.50" in result.content[0].text


async def test_show_dashboard(mcp_client):
    result = await mcp_client.call_tool("show_dashboard", {"symbols": ["AAPL", "MSFT"]})
    visualization = Visualization.model_validate(result.structured_content)
    assert visualization.kind == "workspace"
    assert set(visualization.panels) == {"performance", "volume", "quotes", "prices"}
    assert visualization.layout["type"] == "split-layout"


async def test_view_page(mcp_client):
    result = await mcp_client.call_tool("show_prices", {"symbols": ["AAPL"]})
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as http:
        page = await http.get(f"/view/{result.structured_content['id']}")
        missing = await http.get("/view/unknown")
    assert page.status_code == 200
    assert "<perspective-viewer>" in page.text
    assert '"table":"history/AAPL/ytd/1d"' in page.text
    assert missing.status_code == 404
