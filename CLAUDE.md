# Project rules (set by the owner)

- Don't make big assumptions. Ask for clarification when needed.
- New projects get a git repo.
- Keep answers concise. When asked to explain something, give simple examples.
- Branches: `develop` = testing, `master` = production. Work on `develop`, merge to `master` only after testing.
- More rules will be added during the project.

# Project notes

- Pipeline: Gmail (IMAP) -> parse Bloomberg emails -> Claude (Opus 5.5, structured JSON) -> HTML digest email (SMTP).
- Code lives in `src/digest/`; run with `python -m digest.main` (with `src` on `PYTHONPATH`).
- The repo is **public**: never commit real Bloomberg emails, API keys or `.env`. Real sample emails go in `tests/fixtures/private/` (gitignored).
- ETF tickers come from `config/etf_map.yaml` (curated), not from the model.
