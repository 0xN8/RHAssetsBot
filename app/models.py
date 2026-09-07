"""Tolerant models for Robinhood's public asset response."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Asset:
    asset_id: str
    token_symbol: str | None
    name: str | None
    contract_addresses: tuple[str, ...]
    status: str | None
    multiplier: str | None
    trading_capabilities: Any
    raw: dict[str, Any]

    @classmethod
    def from_api(cls, value: Any) -> "Asset":
        if not isinstance(value, dict):
            raise ValueError("asset must be an object")
        asset_id = value.get("id")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ValueError("asset is missing a non-empty id")
        deployments = value.get("deployments", [])
        if not isinstance(deployments, list):
            deployments = []
        addresses = tuple(
            deployment["contractAddress"]
            for deployment in deployments
            if isinstance(deployment, dict) and isinstance(deployment.get("contractAddress"), str)
        )
        return cls(
            asset_id=asset_id,
            token_symbol=_optional_string(value.get("tokenSymbol")),
            name=_optional_string(value.get("tokenName")) or _optional_string(value.get("name")),
            contract_addresses=addresses,
            status=_optional_string(value.get("status")),
            multiplier=_optional_string(value.get("currentMultiplier")),
            trading_capabilities=value.get("tradingCapabilities"),
            raw=value,
        )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None
