"""Offline tests: parser, DKIM check, rendering. No Gmail or Claude calls.

Uses a synthetic email. To also test real Bloomberg emails, save them as .eml files in
tests/fixtures/private/ (gitignored); test_private_fixtures picks them up automatically.
"""
import email
import io
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path

import pytest
from PIL import Image

from digest.config import load_etf_map
from digest.gmail_client import dkim_ok
from digest.parser import IdCounter, parse_email
from digest.render import render_digest
from digest.schema import DigestAnalysis

HTML = """<html><head><style>.x{}</style></head><body>
<table><tr><td><h1>Markets Daily</h1>
<p>Stocks rose as <b>Nvidia</b> beat estimates. <a href="https://www.bloomberg.com/news/nvda">Read the story</a></p>
<p>The S&amp;P 500 gained 1.2% to 6,100.</p>
<img src="https://assets.example.com/chart1.png" alt="S&amp;P 500 intraday" width="600">
<img src="https://track.example.com/pixel.gif" width="1" height="1">
<p>Treasury 10-year yield fell 5bp to 4.10%. <a href="https://www.bloomberg.com/news/rates">Rates</a></p>
<p><a href="https://www.bloomberg.com/news/nvda">Read the story</a></p>
<p>You received this message because you are subscribed. <a href="https://example.com/unsubscribe">Unsubscribe</a></p>
</td></tr></table></body></html>"""


def _png(w, h):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def fake_fetch(url):
    return _png(640, 320) if "chart" in url else _png(1, 1)


def make_msg(auth="mx.google.com; dkim=pass header.i=@news.bloomberg.com header.s=s1"):
    msg = EmailMessage()
    msg["Subject"] = "Markets Daily: Nvidia lifts stocks"
    msg["From"] = "Bloomberg <noreply@news.bloomberg.com>"
    msg["Date"] = "Tue, 10 Nov 2026 07:00:00 -0500"
    msg["Message-ID"] = "<abc123@news.bloomberg.com>"
    msg["Authentication-Results"] = auth
    msg.set_content("plain version")
    msg.add_alternative(HTML, subtype="html")
    return email.message_from_bytes(msg.as_bytes(), policy=default_policy)


def test_parse_extracts_text_links_and_charts():
    p = parse_email(make_msg(), "E1", "1", IdCounter(), fetch_image=fake_fetch)
    assert "Nvidia beat estimates" in p.text          # inline <b> stays in the sentence
    assert "S&P 500 gained 1.2% to 6,100." in p.text
    assert "Read the story [L1]" in p.text
    assert list(p.links) == ["L1", "L2"]               # duplicate URL reuses L1; unsubscribe skipped
    assert p.links["L2"].url.endswith("/rates")
    assert len(p.charts) == 1 and p.charts[0].id == "C1"   # tracking pixel dropped
    assert "[Chart C1: S&P 500 intraday]" in p.text
    assert "You received this message" not in p.text  # footer trimmed
    assert "rfc822msgid" in p.gmail_url


def test_skip_subscription_subjects():
    from digest.gmail_client import SKIP_SUBJECT_RE
    assert SKIP_SUBJECT_RE.search("You've subscribed!")
    assert SKIP_SUBJECT_RE.search("You’ve subscribed!")
    assert SKIP_SUBJECT_RE.search("Welcome to Markets Daily")
    assert not SKIP_SUBJECT_RE.search("Claude cash")
    assert not SKIP_SUBJECT_RE.search("Stocks welcome Fed cut")


def test_dkim_check():
    assert dkim_ok(make_msg())
    assert not dkim_ok(make_msg("mx.google.com; dkim=fail header.i=@news.bloomberg.com"))
    assert not dkim_ok(make_msg("mx.google.com; dkim=pass header.i=@evil-bloomberg.com.attacker.net"))


def sample_analysis():
    return DigestAnalysis.model_validate({
        "top_takeaways": ["Chip strength lifts US stocks", "Yields ease"],
        "chart_tickers": [],
        "items": [{
            "email_id": "E1",
            "headline": "Nvidia beat lifts stocks",
            "summary": "Nvidia beat estimates; S&P 500 +1.2%.",
            "key_figures": ["S&P 500 +1.2% to 6,100", "UST 10y -5bp to 4.10%"],
            "link_ids": ["L1", "L99"],
            "chart_ids": ["C1"],
            "stocks": [{"ticker": "NVDA", "name": "Nvidia", "signal": "bullish", "reason": "Beat estimates"}],
            "industries": [
                {"sector_key": "semiconductors", "sector_name": "Semis", "signal": "bullish",
                 "reason": "AI demand", "suggested_etfs": []},
                {"sector_key": "space_tech", "sector_name": "Space Tech", "signal": "uncertain",
                 "reason": "Mentioned", "suggested_etfs": [{"ticker": "UFO", "name": "Procure Space", "leverage": "1x"}]},
            ],
            "macro": [{"event": "Yields fall", "market_impact": "Supports growth stocks",
                       "sectors_benefit": ["Tech"], "sectors_hurt": ["Banks"]}],
        }],
    })


def test_render_digest():
    parsed = parse_email(make_msg(), "E1", "1", IdCounter(), fetch_image=fake_fetch)
    msg, preview = render_digest(sample_analysis(), [parsed], [], load_etf_map(), test=True)
    assert msg["Subject"].startswith("[TEST] [BBG Digest]")
    html = msg.get_body(preferencelist=("html",)).get_content()
    for needle in ("Top takeaways", "Nvidia beat lifts stocks", "NVDA", "Bullish", "SOXL", "(3x)",
                   "AI-suggested", "Macro impact", "https://www.bloomberg.com/news/nvda",
                   "cid:c1@bbg-digest", "Markets Daily: Nvidia lifts stocks", "Not financial advice"):
        assert needle in html, needle
    assert "L99" not in html                          # unknown link ids are dropped
    assert "data:image/png;base64" in preview
    related = [p for p in msg.walk() if p.get_content_maintype() == "image"]
    assert len(related) == 1
    text = msg.get_body(preferencelist=("plain",)).get_content()
    assert "S&P 500 +1.2%" in text                    # plain text is not HTML-escaped


PRIVATE = sorted((Path(__file__).parent / "fixtures" / "private").glob("*.eml"))


@pytest.mark.skipif(not PRIVATE, reason="no private Bloomberg .eml fixtures")
@pytest.mark.parametrize("path", PRIVATE, ids=lambda p: p.name)
def test_private_fixtures(path):
    msg = email.message_from_bytes(path.read_bytes(), policy=default_policy)
    p = parse_email(msg, "E1", "1", IdCounter())
    print(f"\n{path.name}: dkim_ok={dkim_ok(msg)} chars={len(p.text)} links={len(p.links)} charts={len(p.charts)}")
    assert len(p.text) > 200
    assert p.links
