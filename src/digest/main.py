"""Entry point: fetch new Bloomberg emails -> analyse with Claude -> email the digest -> label processed."""
from __future__ import annotations

import argparse
import logging
import sys

from .analyser import analyse
from .charts import make_price_charts
from .config import ROOT, load_config, load_etf_map
from .gmail_client import GmailClient, send_email
from .parser import IdCounter, parse_email
from .render import render_digest

log = logging.getLogger("digest")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bloomberg news digest")
    p.add_argument("--dry-run", action="store_true",
                   help="Send a [TEST] digest but do NOT label emails as processed")
    p.add_argument("--no-send", action="store_true",
                   help="Don't send any email; just save out/digest.html for preview")
    p.add_argument("--lookback-days", type=int, default=1,
                   help="Only consider Bloomberg emails newer than this many days (default 1)")
    p.add_argument("--include-processed", action="store_true",
                   help="Also include emails already labelled as processed (useful for testing)")
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    cfg = load_config()
    etf_map = load_etf_map()
    test_mode = args.dry_run or args.no_send

    with GmailClient(cfg) as gmail:
        raw = gmail.fetch_new(args.lookback_days, include_processed=args.include_processed,
                              limit=cfg.max_emails_per_run)
        if not raw:
            log.info("No new Bloomberg emails. Nothing to do.")
            return 0

        ids = IdCounter()
        parsed = [parse_email(r.message, f"E{i}", r.uid, ids) for i, r in enumerate(raw, start=1)]
        for p in parsed:
            log.info("%s: %r | %d chars, %d links, %d charts", p.id, p.subject, len(p.text), len(p.links), len(p.charts))

        analysis = analyse(parsed, etf_map, cfg.model, cfg.effort)
        log.info("Analysis: %d items, %d takeaways", len(analysis.items), len(analysis.top_takeaways))

        price_charts = make_price_charts(analysis.chart_tickers, limit=cfg.max_price_charts)
        msg, preview_html = render_digest(analysis, parsed, price_charts, etf_map,
                                          tz_name=cfg.report_timezone, test=test_mode)

        out_dir = ROOT / "out"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "digest.html").write_text(preview_html, encoding="utf-8")
        (out_dir / "analysis.json").write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        log.info("Saved preview to %s", out_dir / "digest.html")

        if args.no_send:
            log.info("--no-send: not emailing, not labelling.")
            return 0

        send_email(cfg, msg)

        if args.dry_run:
            log.info("--dry-run: emails left unlabelled.")
        else:
            # Only after a successful send, so a failed run is retried next time.
            gmail.mark_processed([r.uid for r in raw])
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
