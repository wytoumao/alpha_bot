# Alpha Listing Reminder Bot

Playwright-based watcher for [alpha123.uk](https://alpha123.uk) that captures daily/upcoming listings and triggers multi-channel notifications through Spug. Designed for unattended operation with cron or container scheduling.

## Features
- Headless Chromium collection with network interception first, DOM fallback second.
- Robust parsing across English and Chinese table layouts.
- Configurable reminder offsets, quiet hours, notification channels, and TBA handling.
- Idempotent state tracking with TTL to avoid duplicate alerts.
- Spug notifier supporting both `/xsend/<user_id>` and `/send/<template_id>` flows with automatic retries.
- Structured logging (JSON via `structlog`) for observability.

## Project Layout
```
collector/           # Playwright entry script, parsing, state, reminder engine
config/              # Environment settings loader
notifier/            # Spug integration
deploy/              # Dockerfile, docker-compose, bootstrap script, cron sample
tests/               # Offline fixtures and unit tests
```

## Prerequisites
- Python 3.9+
- Chromium runtime dependencies (use `playwright install chromium`).
- Access credentials for [push.spug.cc](https://push.spug.cc/) API.

## Quick Start
```bash
git clone https://github.com/wytoumao/alpha_bot.git
cd alpha_bot
bash deploy/bootstrap.sh        # create .venv, install deps, install Playwright browser
cp config/settings.example.env .env
# edit .env with your Spug credentials and reminder preferences
source .venv/bin/activate
python -m collector.alpha_watch
```

The watcher will continue running every minute unless `RUN_ONCE=true` is set. Cron/systemd usage is still recommended for production.

## Configuration
Environment variables (see `config/settings.example.env`):

| Variable | Description |
| --- | --- |
| `ALPHA_URL` | Target site (supports `/zh` or default). |
| `TIMEZONE` | Olson timezone, e.g. `Asia/Taipei`. |
| `AHEAD_MINUTES` | Maximum look-ahead window for reminders. |
| `REMINDER_OFFSETS` | Comma separated offsets (minutes before start). |
| `QUIET_HOURS` | Quiet window, e.g. `00:00-07:30` to downgrade voice calls. |
| `STATE_FILE` | Persistent JSON store for dedupe (defaults to `/data/alpha-state.json`). |
| `PLAYWRIGHT_PROXY` | Optional proxy URI (e.g. `http://127.0.0.1:7891`) for the headless browser. |
| `SPUG_*` | Base URL, token, channel, template, targets, quiet fallback channel. |
| `NOTIFY_TBA_ONCE` | Toggle to alert once for TBA events without start time. |
| `RUN_ONCE` | Force single execution cycle (useful for cron). |

## Scheduling Options
- **Cron**: adapt `deploy/cron.example` to your installation path and append to crontab (`crontab -e`).
- **systemd timer**: create a unit calling the virtualenv python binary every minute.
- **Docker Compose**: populate an `.env` file with variables above and run `docker compose -f deploy/docker-compose.yaml up -d`.

## Logging & Persistence
Logs are JSON structured on stdout (collector status, reminder counts, notification results). Scraped events and pending notifications are persisted in MySQL (see `deploy/schema.sql`) so collectors and notifiers can run independently.

## Tests
Offline unit tests cover JSON/DOM parsing, reminder evaluation, and time utilities.
```bash
source .venv/bin/activate
pytest
```

Fixtures in `tests/fixtures/` provide deterministic HTML/JSON snapshots for regression testing.

## Deployment Checklist
1. Configure `.env` or environment variables (MySQL credentials, Spug token/channel/template, reminder offsets).
2. Apply `deploy/schema.sql` to the target MySQL database.
3. Run `deploy/bootstrap.sh` (or replicate steps) to install dependencies and Playwright browser.
4. Verify a dry-run locally with `RUN_ONCE=true python -m collector.alpha_watch`.
5. Enable scheduler via cron/systemd or build with the provided Dockerfile/Compose stack.
6. Monitor logs and adjust reminder offsets, quiet hours, or Spug channels as needed.
