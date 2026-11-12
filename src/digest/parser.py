"""Turn a Bloomberg newsletter email into clean text + numbered links + chart images."""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from email.message import Message
from typing import Callable, Optional

import requests
from bs4 import BeautifulSoup, NavigableString
from PIL import Image

log = logging.getLogger(__name__)

MIN_CHART_W, MIN_CHART_H = 300, 150   # smaller images are logos/icons/pixels
MAX_IMAGE_SIDE = 1568                 # Claude's recommended max; also keeps emails light
MAX_CHARTS_PER_EMAIL = 8

_SKIP_LINK_RE = re.compile(
    r"unsubscribe|preferences|manage[-_ ]?(your)?[-_ ]?subscriptions?|privacy|terms|"
    r"view[-_ ]?(it )?in[-_ ]?(your )?browser|facebook\.com|twitter\.com|x\.com/|linkedin\.com|"
    r"instagram\.com|youtube\.com|apple\.com/app|play\.google\.com|mailto:|tel:",
    re.I,
)
_SKIP_IMG_RE = re.compile(r"pixel|spacer|logo|icon|tracking|beacon|/open|social|badge|avatar", re.I)
_INVISIBLE_RE = re.compile(r"[​‌‍⁠͏­﻿]")
_BLOCK_TAGS = ["p", "div", "tr", "td", "th", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"]
_FOOTER_MARKERS = ("You received this message because", "You are receiving this", "To unsubscribe")

ImageFetcher = Callable[[str], Optional[bytes]]


@dataclass
class Link:
    id: str
    url: str
    text: str


@dataclass
class Chart:
    id: str
    email_id: str
    url: str
    alt: str
    data: bytes
    media_type: str  # image/png or image/jpeg


@dataclass
class ParsedEmail:
    id: str
    uid: str
    subject: str
    date: str
    message_id: str
    text: str
    links: dict[str, Link] = field(default_factory=dict)
    charts: list[Chart] = field(default_factory=list)

    @property
    def gmail_url(self) -> str:
        mid = self.message_id.strip("<>")
        return f"https://mail.google.com/mail/u/0/#search/rfc822msgid%3A{requests.utils.quote(mid)}" if mid else ""


class IdCounter:
    """Shared counters so link/chart IDs stay unique across all emails in one digest."""

    def __init__(self) -> None:
        self.link = 0
        self.chart = 0

    def next_link(self) -> str:
        self.link += 1
        return f"L{self.link}"

    def next_chart(self) -> str:
        self.chart += 1
        return f"C{self.chart}"


def download_image(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (digest-bot)"})
        if r.ok and r.headers.get("Content-Type", "").startswith("image/"):
            return r.content
    except requests.RequestException as e:
        log.debug("Image download failed %s: %s", url, e)
    return None


def _normalise_image(data: bytes) -> Optional[tuple[bytes, str]]:
    """Return (bytes, media_type) if the image is chart-sized; resize/convert as needed."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001 - not a readable image
        return None
    w, h = img.size
    if w < MIN_CHART_W or h < MIN_CHART_H:
        return None
    fmt = (img.format or "").upper()
    if max(w, h) > MAX_IMAGE_SIDE:
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    elif fmt in ("PNG", "JPEG"):
        return data, f"image/{fmt.lower()}"
    out = io.BytesIO()
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")
    img.save(out, format="PNG", optimize=True)
    return out.getvalue(), "image/png"


def _html_part(msg: Message) -> tuple[str, bool]:
    """Return (body, is_html)."""
    body = msg.get_body(preferencelist=("html", "plain")) if hasattr(msg, "get_body") else None
    if body is None:
        return "", False
    content = body.get_content()
    return content, body.get_content_type() == "text/html"


def _clean_text(text: str) -> str:
    text = _INVISIBLE_RE.sub("", text).replace(" ", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if not ln and (not out or not out[-1]):
            continue
        out.append(ln)
    text = "\n".join(out).strip()
    # Drop the subscription footer when it sits in the last part of the email.
    for marker in _FOOTER_MARKERS:
        pos = text.find(marker)
        if pos != -1 and pos > len(text) * 0.6:
            text = text[:pos].rstrip()
            break
    return text


def parse_email(
    raw_msg: Message,
    email_id: str,
    uid: str,
    ids: IdCounter,
    fetch_image: ImageFetcher = download_image,
) -> ParsedEmail:
    subject = str(raw_msg.get("Subject", "(no subject)"))
    parsed = ParsedEmail(
        id=email_id,
        uid=uid,
        subject=subject,
        date=str(raw_msg.get("Date", "")),
        message_id=str(raw_msg.get("Message-ID", "")),
        text="",
    )
    body, is_html = _html_part(raw_msg)
    if not is_html:
        parsed.text = _clean_text(body)
        return parsed

    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style", "head", "title", "meta"]):
        tag.decompose()

    # Charts first (an <img> may sit inside a link).
    seen_img: set[str] = set()
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        alt = (img.get("alt") or "").strip()
        keep = (
            src.startswith("http")
            and src not in seen_img
            and not _SKIP_IMG_RE.search(src)
            and len(parsed.charts) < MAX_CHARTS_PER_EMAIL
        )
        for dim in ("width", "height"):
            v = str(img.get(dim) or "").rstrip("px")
            if v.isdigit() and int(v) < 60:
                keep = False
        result = None
        if keep:
            seen_img.add(src)
            data = fetch_image(src)
            result = _normalise_image(data) if data else None
        if result:
            cid = ids.next_chart()
            parsed.charts.append(Chart(cid, email_id, src, alt, result[0], result[1]))
            img.replace_with(NavigableString(f"\n[Chart {cid}{': ' + alt if alt else ''}]\n"))
        else:
            img.replace_with(NavigableString(f" {alt} " if alt and len(alt) < 80 else ""))

    url_to_id: dict[str, str] = {}
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        text = " ".join(a.get_text(" ").split())
        if not href.startswith("http") or _SKIP_LINK_RE.search(href) or _SKIP_LINK_RE.search(text):
            a.unwrap()
            continue
        lid = url_to_id.get(href)
        if lid is None:
            lid = ids.next_link()
            url_to_id[href] = lid
            parsed.links[lid] = Link(lid, href, text or "Link")
        a.replace_with(NavigableString(f"{text} [{lid}]" if text else f"[{lid}]"))

    for br in soup.find_all("br"):
        br.replace_with(NavigableString("\n"))
    # Newlines only at block boundaries, so inline text (bold, links) stays in one sentence.
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_after(NavigableString("\n"))
    parsed.text = _clean_text(soup.get_text())
    return parsed
