"""Build the digest email (HTML + plain-text fallback + inline images)."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .charts import PriceChart
from .parser import Chart, ParsedEmail
from .schema import DigestAnalysis, NewsItem

TEMPLATES = Path(__file__).parent / "templates"
SIGNAL_STYLE = {
    "bullish": ("\U0001F7E2", "Bullish", "#e6f4e6"),
    "bearish": ("\U0001F534", "Bearish", "#fbe9e9"),
    "uncertain": ("\U0001F7E1", "Uncertain", "#fdf3dc"),
}


@dataclass
class InlineImage:
    cid: str
    data: bytes
    media_type: str


@dataclass
class ItemView:
    item: NewsItem
    source: ParsedEmail
    source_time: str
    links: list = field(default_factory=list)       # [(text, url)]
    charts: list = field(default_factory=list)      # [(cid, alt)]
    industries: list = field(default_factory=list)  # [dict]


def _fmt_time(date_header: str, tz: ZoneInfo) -> str:
    try:
        return parsedate_to_datetime(date_header).astimezone(tz).strftime("%a %d %b %H:%M %Z")
    except (TypeError, ValueError):
        return date_header


def _cid(name: str) -> str:
    return f"{name.lower()}@bbg-digest"


def build_views(analysis: DigestAnalysis, emails: list[ParsedEmail], etf_map: dict, tz: ZoneInfo):
    by_id = {e.id: e for e in emails}
    charts_by_id: dict[str, Chart] = {c.id: c for e in emails for c in e.charts}
    links_by_id = {lid: link for e in emails for lid, link in e.links.items()}
    used_charts: set[str] = set()
    images: list[InlineImage] = []
    views: list[ItemView] = []

    order = {e.id: i for i, e in enumerate(emails)}
    items = sorted(analysis.items, key=lambda it: order.get(it.email_id, len(order)))
    for it in items:
        src = by_id.get(it.email_id) or emails[0]
        v = ItemView(item=it, source=src, source_time=_fmt_time(src.date, tz))
        for lid in dict.fromkeys(it.link_ids):
            link = links_by_id.get(lid)
            if link:
                v.links.append((link.text[:90], link.url))
        for chid in dict.fromkeys(it.chart_ids):
            ch = charts_by_id.get(chid)
            if ch and chid not in used_charts:
                used_charts.add(chid)
                v.charts.append((_cid(chid), ch.alt))
                images.append(InlineImage(_cid(chid), ch.data, ch.media_type))
        for ind in it.industries:
            mapped = etf_map.get(ind.sector_key)
            etfs = mapped["etfs"] if mapped else [e.model_dump() for e in ind.suggested_etfs]
            v.industries.append({
                "name": mapped["name"] if mapped else ind.sector_name,
                "signal": ind.signal,
                "reason": ind.reason,
                "etfs": etfs,
                "ai_suggested": mapped is None,
            })
        views.append(v)

    # Bloomberg charts no story claimed: show them under the first story from the same email.
    for e in emails:
        leftovers = [c for c in e.charts if c.id not in used_charts]
        target = next((v for v in views if v.source.id == e.id), None)
        if not leftovers or target is None:
            continue
        for c in leftovers:
            used_charts.add(c.id)
            target.charts.append((_cid(c.id), c.alt))
            images.append(InlineImage(_cid(c.id), c.data, c.media_type))
    return views, images


def render_digest(
    analysis: DigestAnalysis,
    emails: list[ParsedEmail],
    price_charts: list[PriceChart],
    etf_map: dict,
    tz_name: str = "UTC",
    test: bool = False,
) -> tuple[EmailMessage, str]:
    """Return (email message ready to send, html string for local preview)."""
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    views, images = build_views(analysis, emails, etf_map, tz)
    price_views = []
    for pc in price_charts:
        cid = _cid(f"px-{pc.ticker.replace('^', '').replace('.', '-')}")
        images.append(InlineImage(cid, pc.png, "image/png"))
        price_views.append({"cid": cid, "ticker": pc.ticker})

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False))
    ctx = dict(
        analysis=analysis, views=views, emails=emails, price_views=price_views,
        signal_style=SIGNAL_STYLE, generated=now.strftime("%a %d %b %Y %H:%M %Z"), test=test,
    )
    html = env.get_template("digest.html.j2").render(**ctx)
    text = env.get_template("digest.txt.j2").render(**ctx)

    n = len(emails)
    subject = f"{'[TEST] ' if test else ''}[BBG Digest] {now.strftime('%d %b %H:%M %Z')} - {n} email{'s' if n != 1 else ''}"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    html_part = msg.get_payload()[1]
    for img in images:
        maintype, subtype = img.media_type.split("/", 1)
        html_part.add_related(img.data, maintype=maintype, subtype=subtype, cid=f"<{img.cid}>")

    # Local preview: point cid: references at data URIs.
    preview = html
    for img in images:
        uri = f"data:{img.media_type};base64,{base64.b64encode(img.data).decode()}"
        preview = preview.replace(f"cid:{img.cid}", uri)
    return msg, preview
