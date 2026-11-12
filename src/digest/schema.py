"""Structured output Claude must return (enforced via structured outputs)."""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

Signal = Literal["bullish", "bearish", "uncertain"]


class StockSignal(BaseModel):
    ticker: str = Field(description="Yahoo Finance symbol, e.g. AAPL, 7203.T, 0700.HK, SAP.DE")
    name: str
    signal: Signal
    reason: str = Field(description="One short line: why, based on the news")


class SuggestedEtf(BaseModel):
    ticker: str
    name: str
    leverage: str = Field(description="1x, 2x, 3x, -1x, -2x or -3x")


class IndustrySignal(BaseModel):
    sector_key: str = Field(description="A key from the sector list, or a new snake_case key if none fits")
    sector_name: str
    signal: Signal
    reason: str
    suggested_etfs: List[SuggestedEtf] = Field(
        description="ONLY when sector_key is not in the sector list: popular ETFs for it; otherwise empty"
    )


class MacroImpact(BaseModel):
    event: str = Field(description="The economic/policy news, with the key number vs. expectations if given")
    market_impact: str = Field(description="Likely effect on rates, FX, equities, commodities")
    sectors_benefit: List[str]
    sectors_hurt: List[str]


class NewsItem(BaseModel):
    email_id: str = Field(description="Source email id, e.g. E1")
    headline: str
    summary: str = Field(description="1-3 concise sentences on what happened and why it matters")
    key_figures: List[str] = Field(description="Numbers useful for trading: levels, % moves, yields, FX, EPS vs est.")
    link_ids: List[str] = Field(description="Link ids like L3 from the email text relevant to this item")
    chart_ids: List[str] = Field(description="Chart ids like C2 from the email relevant to this item")
    stocks: List[StockSignal]
    industries: List[IndustrySignal]
    macro: List[MacroImpact]


class DigestAnalysis(BaseModel):
    top_takeaways: List[str] = Field(description="3-5 bullets: the most actionable implications across all emails")
    items: List[NewsItem]
    chart_tickers: List[str] = Field(
        description="Up to 6 Yahoo Finance symbols (stocks/ETFs/indices like ^GSPC) most worth a 1-month price chart"
    )
