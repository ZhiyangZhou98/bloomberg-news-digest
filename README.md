# Bloomberg News Digest

Every 15 minutes, GitHub Actions checks Gmail for new Bloomberg newsletter emails (`noreply@news.bloomberg.com`).
Claude (Opus 5.5) analyses them, and you get one digest email back with:

- top takeaways
- per story: summary, key figures, Bloomberg's charts, links to the full stories and to the source email
- 🟢 bullish / 🔴 bearish / 🟡 uncertain signals for every stock and industry mentioned, with popular ETFs (leveraged and inverse included)
- macro impact: which sectors benefit and which are hurt
- 1-month price charts for the most relevant tickers

Processed emails get the Gmail label `BBG-Digest-Processed`, so nothing is analysed twice. If no new emails arrived, nothing is sent.

## How it works

```
Gmail (IMAP) -> parser.py -> analyser.py (Claude) -> charts.py (yfinance) -> render.py -> Gmail (SMTP) -> label processed
```

| File | Job |
|---|---|
| `src/digest/gmail_client.py` | search/fetch Bloomberg emails (kept unread), DKIM check, label, send |
| `src/digest/parser.py` | HTML -> text with `[L#]` link and `[Chart C#]` markers; downloads chart images |
| `src/digest/analyser.py` | one Claude call per run with all emails + chart images; structured JSON output |
| `src/digest/schema.py` | the JSON structure Claude must return |
| `config/etf_map.yaml` | curated sector -> ETF tickers (edit freely) |
| `src/digest/render.py`, `templates/` | the HTML/plain-text email |

## One-time setup

### 1. Gmail App Password
1. Turn on 2-Step Verification: <https://myaccount.google.com/signinoptions/twosv>
2. Create an App Password (name it "bbg-digest"): <https://myaccount.google.com/apppasswords>. Copy the 16 letters.
3. Gmail → Settings → *Forwarding and POP/IMAP* → make sure IMAP is enabled.

### 2. Anthropic API key (pay-as-you-go, separate from a Claude.ai subscription)
1. Sign up at <https://console.anthropic.com>.
2. *Billing*: add a payment method and buy credits (e.g. $20 to start).
3. *Limits*: set a **monthly spend limit** (e.g. $50) so costs can't run away.
4. *API keys*: create a key and copy it (`sk-ant-...`).

Expected cost: about $0.15 per Bloomberg email, so roughly $25–45/month at ~8 emails/day.
Each run logs its token use and cost, and the Console's *Usage* page shows totals.

### 3. GitHub secrets
In the repo: *Settings → Secrets and variables → Actions → New repository secret*:

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your `sk-ant-...` key |
| `GMAIL_ADDRESS` | your Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-letter app password |

Optional: under the *Variables* tab, add `REPORT_TIMEZONE` (e.g. `Asia/Singapore`, `Europe/London`) for the times shown in the email. The default is UTC.

### 4. Test, then go live
1. *Actions → Bloomberg digest → Run workflow* on the **develop** branch (dry run). You get a `[TEST]` email, and nothing gets labelled.
2. When happy, merge `develop` into `master`. The 15-min schedule only runs on `master`.

## Running locally (Windows)

```powershell
cd e:\Zhiyang\CodingProjects\bloomberg-news-digest
copy .env.example .env      # then fill in the 3 values
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m pytest -q                                   # offline tests
python -m digest.main --no-send --lookback-days 2     # analyse, save out\digest.html only
python -m digest.main --dry-run --lookback-days 2     # also email a [TEST] digest
python -m digest.main                                 # production: send + label
```

Flags: `--dry-run` (send, don't label), `--no-send` (preview only), `--lookback-days N`, `--include-processed`.

To test the parser on real emails: in Gmail open a Bloomberg email → ⋮ → *Download message*. Put the `.eml` file in
`tests/fixtures/private/` (gitignored) and run `pytest -s`.

## Branches
- `develop`: testing. Pushes run the tests, and manual workflow runs here are always dry runs.
- `master`: production. The schedule runs here.

## Notes
- GitHub's scheduler can run 5–15 min late at busy times.
- Public repos get unlimited free Actions minutes. Secrets stay encrypted, and no email content is stored in the repo.
- GitHub pauses schedules after 60 days without repo activity. The workflow re-enables itself daily to prevent that,
  and GitHub also emails a warning first.
- Price data comes from Yahoo Finance via `yfinance` (unofficial). If it fails, the charts are skipped and the digest is still sent.
- Signals are AI-generated from the news only. Not financial advice.
