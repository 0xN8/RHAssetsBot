"""Codex-domain values. Addresses are always canonicalised before persistence."""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

def normalize_address(address: str) -> str:
    return address.strip().lower()

class MemeClassification(StrEnum):
    MEME = "MEME"
    NOT_MEME = "NOT_MEME"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class CodexToken:
    network_id: int
    address: str
    symbol: str | None = None
    name: str | None = None
    created_at: int | None = None
    total_supply: float | None = None
    categories: tuple[str, ...] = ()
    raw: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, value: dict[str, Any], network_id: int) -> "CodexToken":
        info = value.get("info") if isinstance(value.get("info"), dict) else {}
        return cls(network_id, normalize_address(value["address"]), value.get("symbol"), value.get("name"),
                   _integer(value.get("createdAt")), _number(info.get("totalSupply")),
                   tuple(str(c.get("id", "")).lower() for c in value.get("categories", []) if isinstance(c, dict)), value)

@dataclass(frozen=True)
class CodexPair:
    network_id: int
    address: str
    pair_id: str
    token0: str
    token1: str
    protocol: str | None = None
    fee: int | None = None
    created_at: int | None = None
    liquidity_usd: float | None = None
    volume_usd: float | None = None
    exchange_id: str | None = None
    raw: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, value: dict[str, Any]) -> "CodexPair":
        address, network_id = value["address"], int(value["networkId"])
        return cls(network_id, normalize_address(address), value.get("id") or f"{address}:{network_id}",
                   normalize_address(value["token0"]), normalize_address(value["token1"]), value.get("protocol"),
                   _integer(value.get("fee")), _integer(value.get("createdAt")), _number(value.get("liquidity")),
                   _number(value.get("volume24")), value.get("exchangeId"), value)

def _number(v: Any) -> float | None:
    try: return float(v) if v is not None else None
    except (TypeError, ValueError): return None
def _integer(v: Any) -> int | None:
    try: return int(v) if v is not None else None
    except (TypeError, ValueError): return None
