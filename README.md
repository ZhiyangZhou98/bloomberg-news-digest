# Bloomberg News Digest

When a new Bloomberg newsletter email (`noreply@news.bloomberg.com`) arrives, a small Google Apps Script notices it
(it checks Gmail every 5 minutes) and starts the GitHub Actions workflow.
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
2. When happy, merge `develop` into `master`.

### 5. Trigger (Google Apps Script)
GitHub's built-in scheduler has been unreliable since Aug 2026: scheduled runs come hours late or never start.
The real trigger is therefore `apps_script/Code.gs`, which runs in your Google account.

1. **GitHub token.** Go to GitHub → Settings → Developer settings → *Fine-grained tokens* → *Generate new token*.
   - Name: `bbg-digest-trigger`. Expiration: up to 1 year (set a calendar reminder to renew it).
   - Repository access: *Only select repositories* → `bloomberg-news-digest`.
   - Permissions → Repository → **Actions: Read and write**. Nothing else.
   - Copy the token (`github_pat_...`).
2. **Script.** Go to <https://script.google.com> → *New project*, and rename it `BBG Digest Trigger`.
   Replace the contents of `Code.gs` with this repo's `apps_script/Code.gs`, then save.
3. **Token property.** *Project Settings* (gear icon) → *Script Properties* → add `GITHUB_TOKEN` = your token.
4. **Test.** In the editor, pick `testDispatch` → *Run*, and allow Gmail/external-request access when asked
   (Google shows an "unverified app" warning for your own scripts: *Advanced* → *Go to BBG Digest Trigger*).
   A dry run starts on `develop`, and a `[TEST]` digest arrives in a few minutes.
5. **Go live.** Pick `setup` → *Run*. This creates the 5-minute trigger. Check it under *Triggers* (clock icon).

How it works: the script runs every 5 min and dispatches a production run only when there is a Bloomberg email
without the `BBG-Digest-Processed` label. If an email is still unprocessed 45 min after a dispatch, it retries
(up to 3 times). If dispatching fails (e.g. the token expired), it emails you, at most once a day.

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
- `master`: production. The Apps Script trigger (and GitHub's cron backstop) run here.

## Notes
- Digests usually arrive 5–10 min after the Bloomberg email: up to 5 min for the trigger plus ~3 min for the run.
- The GitHub cron schedule is kept only as a backstop. Duplicates are impossible because emails are labelled after each digest.
- Public repos get unlimited free Actions minutes. Secrets stay encrypted, and no email content is stored in the repo.
- GitHub disables workflows with a schedule after 60 days without repo commits. Each production run re-enables the
  workflow to prevent that, and GitHub also emails a warning first.
- Price data comes from Yahoo Finance via `yfinance` (unofficial). If it fails, the charts are skipped and the digest is still sent.
- Signals are AI-generated from the news only. Not financial advice.
