# itec-watcher

Watches the iTEC FURG vacancies page (https://itecfurg.org/?page_id=2695) every 5 minutes and posts to a Telegram channel when a new listing appears or a listing changes status (open, closed, result available). Summaries are rule-based, no LLM.

## Telegram setup

1. Create a dedicated bot with @BotFather and copy the token.
2. Add the bot to the channel as admin with only the "Post messages" right.
3. Channel id: `-100...` for private channels, or `@channelname` for public ones.
4. Optional: `TELEGRAM_ADMIN_CHAT_ID` is a chat that receives plain-text alerts (start, bulk listings, 6 failed cycles in a row, recovery). Message the bot once from that chat first.

## Configuration

Copy `.env.example` to `.env` on the host and fill it in. Keep it out of git and set mode 600:

    chmod 600 .env

Variables: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ADMIN_CHAT_ID` (optional), `DEPLOY_HOST` (ssh target, e.g. `user@host`; only needed in the local `.env` used for deploying). All other settings are constants in `watcher/config.py`.

## Deploy

    set -a; . ./.env; set +a
    rsync -av --delete --exclude .env --exclude .git --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude data/ --exclude tests/ ./ "$DEPLOY_HOST":~/itec-watcher/
    ssh "$DEPLOY_HOST" 'cd ~/itec-watcher && docker compose up -d --build'

Create `.env` on the host once.

The first run seeds the current listings silently. Nothing is posted to the channel for them.

## Operations

Logs:

    docker compose logs -f watcher

Send a test message to the channel:

    docker compose run --rm watcher python -m watcher.send_test

The healthcheck checks that `/data/heartbeat` was updated in the last 15 minutes. It is informational only: Docker without swarm does not restart unhealthy containers. The admin alert is the real failure signal.

Stop: `docker compose down` (the data volume is kept).

Full reset (the next run seeds silently again):

    docker compose down && docker volume rm itec-watcher_itec-watcher-data

Corrupt state: if the logs show "state unreadable", the watcher refuses to reseed on its own. Either fix `/data/state.json` or do a full reset. A reset means listings published while the watcher was down are not announced.

## Development

    python -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/python -m pytest -q

Tests are offline and use the saved pages in `tests/fixtures/`.
