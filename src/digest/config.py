"""Settings loaded from environment variables (or a local .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
ETF_MAP_PATH = ROOT / "config" / "etf_map.yaml"


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    gmail_address: str
    gmail_app_password: str
    report_to: str
    bloomberg_sender: str
    processed_label: str
    model: str
    effort: str
    require_dkim: bool
    max_emails_per_run: int
    max_price_charts: int
    report_timezone: str


def load_config() -> Config:
    load_dotenv(ROOT / ".env")
    missing = [k for k in ("ANTHROPIC_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"Missing required settings: {', '.join(missing)} (set them in .env or GitHub Secrets)")
    address = os.environ["GMAIL_ADDRESS"].strip()
    return Config(
        gmail_address=address,
        gmail_app_password=os.environ["GMAIL_APP_PASSWORD"].replace(" ", ""),
        report_to=os.getenv("REPORT_TO") or address,
        bloomberg_sender=os.getenv("BLOOMBERG_SENDER") or "noreply@news.bloomberg.com",
        processed_label=os.getenv("PROCESSED_LABEL") or "BBG-Digest-Processed",
        model=os.getenv("CLAUDE_MODEL") or "claude-opus-5-5",
        effort=os.getenv("CLAUDE_EFFORT") or "medium",
        require_dkim=_bool(os.getenv("REQUIRE_DKIM"), True),
        max_emails_per_run=int(os.getenv("MAX_EMAILS_PER_RUN") or 12),
        max_price_charts=int(os.getenv("MAX_PRICE_CHARTS") or 6),
        report_timezone=os.getenv("REPORT_TIMEZONE") or "UTC",
    )


def load_etf_map(path: Path = ETF_MAP_PATH) -> dict:
    """Return {sector_key: {"name": str, "etfs": [{"ticker", "name", "leverage"}]}}."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["sectors"]
