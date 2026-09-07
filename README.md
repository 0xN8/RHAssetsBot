# Robinhood Stock Token Monitor

A small Python service that polls Robinhood's public `GET https://api.robinhood.com/rhj/assets` endpoint and sends a Telegram alert when Robinhood adds an official Stock Token (a tokenized stock or ETF) to that endpoint.

It also has an optional Codex worker that discovers **separate memecoins** directly paired with a Stock Token on Robinhood Chain. It never records infrastructure/stablecoin/Stock-Token pairs as meme associations.

## Observed endpoint schema

The live response inspected on 2026-09-03 is an object with an `assets` array. Each asset includes a stable `id`, `tokenSymbol`, `tokenName`, `deployments` (with `contractAddress`, `chainId`, and `networkName`), `currentMultiplier`, `status`, and `tradingCapabilities`. The parser accepts optional and extra fields, and preserves the complete JSON for each asset.

## Setup

```bash
cd robinhood-token-monitor
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Export the settings (or load them with your preferred environment manager):

```bash
export TELEGRAM_BOT_TOKEN='123456:token-from-botfather'
export TELEGRAM_CHAT_ID='your-chat-id'
export POLL_INTERVAL_SECONDS=5
export DATABASE_PATH=./data/robinhood_tokens.db
export CODEX_API_KEY='your-codex-key'
python -m app.main
```

Create a Telegram bot by messaging [@BotFather](https://t.me/BotFather), choosing `/newbot`, and copying the token it gives you. Send a message to the bot, then obtain its chat ID from `https://api.telegram.org/bot<TOKEN>/getUpdates` (the `message.chat.id` field). Treat the token as a secret and never commit `.env`.

On the first successful poll, the service writes all existing assets as a baseline and sends no new-asset alerts. Later discoveries are persisted before Telegram delivery. Failed Telegram sends remain pending and are retried without treating the asset as newly discovered again.

The monitor also sends an operational Telegram message after its first successful Robinhood poll and after recovery from one or more Robinhood API failures. Meaningful Stock Token metadata changes (contract deployment, status, multiplier, or trading capability) generate a separate Telegram message; delivery failures are logged and never stop polling.

SQLite state is stored at `DATABASE_PATH` (default: `./data/robinhood_tokens.db`). It contains the first-seen raw endpoint JSON, metadata, and alert delivery state.

## Codex memecoin discovery

Set `CODEX_API_KEY` to enable the separate worker. It uses Codex `listPairsForToken` for canonical token0/token1 orientation, Codex `token` category metadata for conservative classification, `pairMetadata` for liquidity, and pool-specific `getBars` ATH scans. Results mean all **currently Codex-indexed** pairs within the configured `CODEX_PAIR_LIMIT` (currently 500 in code); Codex does not index some brand-new or minimal-liquidity pools immediately.

Only Codex's `memes` category is accepted as MEME. Existing official Stock Token contracts and Codex stablecoin/infrastructure categories are rejected; insufficient metadata remains an UNKNOWN candidate for recheck. ATH market cap is price × the current Codex total supply, so it is an estimate if supply has changed historically. The scanner retains the earliest timestamp when equal ATH highs occur.

## Tests

```bash
python -m unittest discover -s tests -v
```

The design separates endpoint fetching, normalization, persistence, alerting, and polling, leaving room for a future on-chain registry monitor without conflating it with separate meme/crypto-token monitoring.
