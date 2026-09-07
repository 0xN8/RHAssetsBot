"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    poll_interval_seconds: float
    database_path: Path
    codex_api_key: str | None
    robinhood_network_id: int
    new_stock_token_window_hours: float
    new_stock_token_codex_poll_seconds: float
    established_stock_token_codex_poll_seconds: float
    ath_default_resolution: str
    codex_pair_limit: int

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        interval_raw = os.getenv("POLL_INTERVAL_SECONDS", "5")
        try:
            interval = float(interval_raw)
        except ValueError as exc:
            raise ValueError("POLL_INTERVAL_SECONDS must be a positive number") from exc
        if interval <= 0:
            raise ValueError("POLL_INTERVAL_SECONDS must be a positive number")
        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            poll_interval_seconds=interval,
            database_path=Path(os.getenv("DATABASE_PATH", "./data/robinhood_tokens.db")),
            codex_api_key=os.getenv("CODEX_API_KEY") or None,
            robinhood_network_id=int(os.getenv("ROBINHOOD_NETWORK_ID", "4663")),
            new_stock_token_window_hours=float(os.getenv("NEW_STOCK_TOKEN_WINDOW_HOURS", "24")),
            new_stock_token_codex_poll_seconds=float(os.getenv("NEW_STOCK_TOKEN_CODEX_POLL_SECONDS", "15")),
            established_stock_token_codex_poll_seconds=float(os.getenv("ESTABLISHED_STOCK_TOKEN_CODEX_POLL_SECONDS", "600")),
            ath_default_resolution=os.getenv("ATH_DEFAULT_RESOLUTION", "60"),
            codex_pair_limit=int(os.getenv("CODEX_PAIR_LIMIT", "500")),
        )
