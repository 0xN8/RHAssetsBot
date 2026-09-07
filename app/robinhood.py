"""Robinhood public assets client."""

from __future__ import annotations

import logging
from typing import Any

import requests

from .models import Asset

ASSETS_URL = "https://api.robinhood.com/rhj/assets"


class RobinhoodClient:
    def __init__(self, session: requests.Session | None = None, timeout: tuple[float, float] = (5, 20)) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.setdefault("Accept", "application/json")
        self.session.headers.setdefault("User-Agent", "robinhood-stock-token-monitor/1.0")

    def fetch_assets(self) -> list[Asset]:
        response = self.session.get(ASSETS_URL, timeout=self.timeout)
        response.raise_for_status()
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise ValueError("Robinhood returned malformed JSON") from exc
        raw_assets = _extract_assets(payload)
        assets: list[Asset] = []
        invalid = 0
        for value in raw_assets:
            try:
                assets.append(Asset.from_api(value))
            except ValueError:
                invalid += 1
        if invalid:
            logging.warning("Ignored %d malformed asset record(s)", invalid)
        if not assets and raw_assets:
            raise ValueError("Robinhood response contained no valid asset records")
        return assets


def _extract_assets(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("assets", "data", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError("Robinhood response has no recognizable asset list")
