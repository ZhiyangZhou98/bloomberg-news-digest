"""Read Bloomberg emails over IMAP, label them as processed, and send the digest over SMTP."""
from __future__ import annotations

import email
import imaplib
import logging
import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage, Message
from email.policy import default as default_policy

from .config import Config

log = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"

# Authentication-Results must show a passing DKIM signature from a Bloomberg domain.
_DKIM_RE = re.compile(r"dkim=pass[^;]*header\.(?:i|d)=@?(?:[\w-]+\.)*bloomberg\.(?:com|net)\b", re.I)


@dataclass
class RawEmail:
    uid: str
    message: Message

    @property
    def subject(self) -> str:
        return str(self.message.get("Subject", "(no subject)"))

    @property
    def date(self) -> str:
        return str(self.message.get("Date", ""))

    @property
    def message_id(self) -> str:
        return str(self.message.get("Message-ID", "")).strip()


def dkim_ok(msg: Message) -> bool:
    results = " ".join(str(h) for h in (msg.get_all("Authentication-Results") or []))
    return bool(_DKIM_RE.search(results))


class GmailClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.imap: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "GmailClient":
        self.imap = imaplib.IMAP4_SSL(IMAP_HOST)
        self.imap.login(self.cfg.gmail_address, self.cfg.gmail_app_password)
        mailbox = self._all_mail_mailbox()
        typ, _ = self.imap.select(mailbox, readonly=False)
        if typ != "OK":
            raise RuntimeError(f"Could not open mailbox {mailbox}")
        log.info("Opened mailbox %s", mailbox)
        return self

    def __exit__(self, *exc) -> None:
        if self.imap is not None:
            try:
                self.imap.logout()
            except Exception:  # noqa: BLE001 - best-effort close
                pass

    def _all_mail_mailbox(self) -> str:
        """Find Gmail's 'All Mail' folder (name varies by language), so archived emails are seen too."""
        typ, boxes = self.imap.list()
        if typ == "OK":
            for raw in boxes or []:
                line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
                if "\\All" in line:
                    m = re.search(r'"([^"]+)"\s*$', line) or re.search(r"(\S+)\s*$", line)
                    if m:
                        return f'"{m.group(1)}"'
        return "INBOX"

    def fetch_new(self, lookback_days: int, include_processed: bool = False, limit: int = 12) -> list[RawEmail]:
        """Bloomberg emails from the last N days that don't have the processed label (oldest first)."""
        query = f"from:{self.cfg.bloomberg_sender} newer_than:{lookback_days}d"
        if not include_processed:
            query += f" -label:{self.cfg.processed_label}"
        typ, data = self.imap.uid("SEARCH", "X-GM-RAW", f'"{query}"')
        if typ != "OK":
            raise RuntimeError(f"IMAP search failed: {data}")
        uids = data[0].split() if data and data[0] else []
        log.info("Search %r -> %d email(s)", query, len(uids))
        if len(uids) > limit:
            log.info("Processing the oldest %d now; the rest wait for the next run", limit)
            uids = uids[:limit]

        emails: list[RawEmail] = []
        for uid in uids:
            uid_s = uid.decode()
            # BODY.PEEK keeps the email unread in Gmail.
            typ, parts = self.imap.uid("FETCH", uid_s, "(BODY.PEEK[])")
            if typ != "OK" or not parts or not isinstance(parts[0], tuple):
                log.warning("Could not fetch UID %s", uid_s)
                continue
            msg = email.message_from_bytes(parts[0][1], policy=default_policy)
            if self.cfg.require_dkim and not dkim_ok(msg):
                log.warning("Skipping UID %s (%s): no passing Bloomberg DKIM signature", uid_s, msg.get("Subject"))
                continue
            emails.append(RawEmail(uid=uid_s, message=msg))
        return emails

    def mark_processed(self, uids: list[str]) -> None:
        if not uids:
            return
        label = self.cfg.processed_label
        self.imap.create(label)  # creates the Gmail label; harmless "already exists" error otherwise
        typ, data = self.imap.uid("STORE", ",".join(uids), "+X-GM-LABELS", f"({label})")
        if typ != "OK":
            raise RuntimeError(f"Could not apply label {label}: {data}")
        log.info("Labelled %d email(s) as %s", len(uids), label)


def send_email(cfg: Config, msg: EmailMessage) -> None:
    msg["From"] = cfg.gmail_address
    msg["To"] = cfg.report_to
    with smtplib.SMTP_SSL(SMTP_HOST, 465) as smtp:
        smtp.login(cfg.gmail_address, cfg.gmail_app_password)
        smtp.send_message(msg)
    log.info("Sent digest to %s", cfg.report_to)
