"""Small 1-month price charts (PNG) for the tickers Claude picked, using yfinance data."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

log = logging.getLogger(__name__)

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
LINE = "#2a78d6"


@dataclass
class PriceChart:
    ticker: str
    png: bytes
    last: float
    change_pct: float


def _render(ticker: str, dates, closes) -> bytes:
    first, last = float(closes.iloc[0]), float(closes.iloc[-1])
    change = (last / first - 1) * 100
    fig, ax = plt.subplots(figsize=(6, 2.4), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.plot(dates, closes, color=LINE, linewidth=2, solid_capstyle="round")
    ax.scatter([dates[-1]], [last], s=24, color=LINE, zorder=3, edgecolors=SURFACE, linewidths=2)
    ax.set_title(f"{ticker}  {last:,.2f}  ({change:+.1f}% 1M)", loc="left", fontsize=10, color=INK, fontweight="bold")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    return buf.getvalue()


def make_price_charts(tickers: list[str], limit: int = 6) -> list[PriceChart]:
    """Best effort: a ticker whose data can't be fetched is skipped, never fatal."""
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance not installed; skipping price charts")
        return []
    charts: list[PriceChart] = []
    seen: set[str] = set()
    for t in tickers:
        t = t.strip().upper()
        if not t or t in seen or len(charts) >= limit:
            continue
        seen.add(t)
        try:
            hist = yf.Ticker(t).history(period="1mo", interval="1d", auto_adjust=True)
            closes = hist["Close"].dropna()
            if len(closes) < 3:
                log.info("Not enough price data for %s", t)
                continue
            png = _render(t, closes.index.to_pydatetime(), closes)
            first, last = float(closes.iloc[0]), float(closes.iloc[-1])
            charts.append(PriceChart(t, png, last, (last / first - 1) * 100))
        except Exception as e:  # noqa: BLE001 - yfinance can fail in many ways
            log.warning("Price chart for %s failed: %s", t, e)
    return charts
