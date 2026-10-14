"""Yahoo Finance data as tidy DataFrames, ready to be hosted as Perspective tables."""

from dataclasses import dataclass
from typing import Literal

import pandas as pd
import yfinance as yf

Period = Literal["1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y", "10y", "max"]
Interval = Literal["1d", "1wk", "1mo"]

PRICE_COLUMNS = ["Date", "Symbol", "Open", "High", "Low", "Close", "Volume", "Change %"]
QUOTE_FIELDS = {
    "shortName": "Name",
    "quoteType": "Type",
    "currency": "Currency",
    "regularMarketPrice": "Price",
    "regularMarketChangePercent": "Day %",
    "marketCap": "Market Cap",
    "trailingPE": "P/E",
    "forwardPE": "Forward P/E",
    "dividendYield": "Dividend %",
    "fiftyTwoWeekLow": "52w Low",
    "fiftyTwoWeekHigh": "52w High",
    "sector": "Sector",
}
TEXT_COLUMNS = {"Symbol", "Name", "Type", "Currency", "Sector"}


@dataclass
class SymbolMatch:
    symbol: str
    name: str
    type: str
    exchange: str


def search(query: str, limit: int = 8) -> list[SymbolMatch]:
    return [
        SymbolMatch(
            symbol=quote["symbol"],
            name=quote.get("shortname") or quote.get("longname") or "",
            type=quote.get("quoteType", ""),
            exchange=quote.get("exchDisp") or quote.get("exchange", ""),
        )
        for quote in yf.Search(query, max_results=limit).quotes
        if "symbol" in quote
    ]


def history(symbols: list[str], period: Period = "ytd", interval: Interval = "1d") -> pd.DataFrame:
    prices = yf.download(
        symbols, period=period, interval=interval, auto_adjust=True, progress=False, multi_level_index=True
    ).dropna(how="all")
    if prices.empty:
        raise ValueError(f"Yahoo Finance has no {period} prices for {', '.join(symbols)}")
    tidy = (
        prices.stack(level="Ticker", future_stack=True)
        .reset_index()
        .rename(columns={"Ticker": "Symbol"})
        .dropna(subset=["Close"])
        .sort_values(["Symbol", "Date"], ignore_index=True)
    )
    tidy["Date"] = tidy["Date"].dt.date
    tidy["Change %"] = 100 * (tidy["Close"] / tidy.groupby("Symbol")["Close"].transform("first") - 1)
    return tidy[PRICE_COLUMNS]


def quotes(symbols: list[str]) -> pd.DataFrame:
    infos = {symbol: yf.Ticker(symbol).info for symbol in symbols}
    rows = [
        {"Symbol": symbol} | {label: info.get(field) for field, label in QUOTE_FIELDS.items()}
        for symbol, info in infos.items()
        if info.get("regularMarketPrice") is not None
    ]
    if not rows:
        raise ValueError(f"Yahoo Finance has no quotes for {', '.join(symbols)}")
    frame = pd.DataFrame(rows, columns=["Symbol", *QUOTE_FIELDS.values()])
    return frame.astype({column: "string" if column in TEXT_COLUMNS else "float64" for column in frame.columns})
