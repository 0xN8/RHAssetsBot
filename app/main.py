"""Polling loop and detection coordination."""

from __future__ import annotations

import logging
import time
from typing import Callable

import requests

from .config import Config
from .database import Database
from .robinhood import RobinhoodClient
from .telegram import TelegramClient
from .codex import CodexClient
from .meme_monitor import CodexMemeWorker

LOG = logging.getLogger(__name__)


class Monitor:
    def __init__(self, database: Database, robinhood: RobinhoodClient, telegram: TelegramClient | None) -> None:
        self.database = database
        self.robinhood = robinhood
        self.telegram = telegram

    def poll_once(self) -> None:
        assets = self.robinhood.fetch_assets()
        if not self.database.baseline_initialized():
            for asset in assets:
                self.database.insert_asset(asset, alert_state="baseline")
            self.database.mark_baseline_initialized()
            LOG.info("Created first-run baseline with %d existing Stock Tokens; no alerts sent", len(assets))
            return
        new_assets = []
        for asset in assets:
            if not self.database.has_asset(asset.asset_id):
                self.database.insert_asset(asset)  # Persist before notifying: discovery is durable.
                new_assets.append(asset)
                LOG.info("New Stock Token discovered: %s (%s)", asset.token_symbol or "unknown", asset.asset_id)
            else:
                changes = self.database.update_asset(asset)
                meaningful = {"contract_address", "status", "multiplier", "trading_capabilities"}.intersection(changes)
                if meaningful:
                    LOG.info("Metadata changed for %s: %s", asset.asset_id, ", ".join(sorted(meaningful)))
                    if self.telegram:
                        try:
                            self.telegram.send_metadata_change_alert(asset, meaningful)
                        except (requests.RequestException, ValueError, RuntimeError) as exc:
                            LOG.error("Metadata-change Telegram delivery failed for %s: %s", asset.asset_id, exc)
        if new_assets:
            LOG.info("Detected %d new Stock Token(s)", len(new_assets))
        self._deliver_pending_alerts()

    def _deliver_pending_alerts(self) -> None:
        pending = self.database.pending_alerts()
        if not pending:
            return
        if self.telegram is None:
            LOG.warning("%d alert(s) pending; Telegram is not configured", len(pending))
            return
        for asset in pending:
            self.database.record_alert_attempt(asset.asset_id)
            try:
                self.telegram.send_asset_alert(asset)
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                self.database.record_alert_error(asset.asset_id, str(exc))
                LOG.error("Telegram delivery failed for %s: %s", asset.asset_id, exc)
            else:
                self.database.mark_alert_sent(asset.asset_id)
                LOG.info("Telegram alert delivered for %s", asset.asset_id)


def run_forever(config: Config, sleep: Callable[[float], None] = time.sleep) -> None:
    database = Database(config.database_path)
    telegram = TelegramClient(config.telegram_bot_token, config.telegram_chat_id) if config.telegram_bot_token and config.telegram_chat_id else None
    if telegram is None:
        LOG.warning("Telegram is unconfigured; discoveries will be stored as pending alerts")
    monitor = Monitor(database, RobinhoodClient(), telegram)
    codex_worker = (CodexMemeWorker(database, CodexClient(config.codex_api_key, pair_limit=config.codex_pair_limit), telegram, config.robinhood_network_id,
                                    config.new_stock_token_window_hours, config.ath_default_resolution)
                    if config.codex_api_key else None)
    if codex_worker is None:
        LOG.warning("CODEX_API_KEY is unconfigured; Codex memecoin discovery is disabled")
    failures = 0
    has_successful_poll = False
    LOG.info("Starting Robinhood Stock Token monitor; database=%s interval=%ss", config.database_path, config.poll_interval_seconds)
    try:
        while True:
            try:
                monitor.poll_once()
                if codex_worker:
                    codex_worker.run_due(config.new_stock_token_codex_poll_seconds, config.established_stock_token_codex_poll_seconds)
            except (requests.RequestException, ValueError) as exc:
                failures += 1
                delay = min(config.poll_interval_seconds * (2 ** min(failures - 1, 5)), 300)
                LOG.warning("Robinhood poll failed (%s); retrying in %ss", exc, delay)
                sleep(delay)
                continue
            if not has_successful_poll:
                _send_status_alert(telegram, "Monitor started; first Robinhood poll completed successfully.")
                has_successful_poll = True
            elif failures:
                LOG.info("Robinhood API recovered after %d failed poll(s)", failures)
                _send_status_alert(telegram, f"Robinhood API connection restored after {failures} failed poll(s).")
                failures = 0
            sleep(config.poll_interval_seconds)
    finally:
        database.close()


def _send_status_alert(telegram: TelegramClient | None, message: str) -> None:
    if telegram is None:
        return
    try:
        telegram.send_status_alert(message)
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        LOG.error("Operational-status Telegram delivery failed: %s", exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_forever(Config.from_env())


if __name__ == "__main__":
    main()
