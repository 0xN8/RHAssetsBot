"""Deliberately conservative category-based memecoin classification."""
from __future__ import annotations
from dataclasses import dataclass
from .codex_models import CodexToken, MemeClassification, normalize_address

@dataclass(frozen=True)
class Classification:
    value: MemeClassification; reason: str; source: str

class MemeClassifier:
    def __init__(self, stock_addresses: set[str]) -> None: self.stock_addresses={normalize_address(x) for x in stock_addresses}
    def classify(self, token: CodexToken | None) -> Classification:
        if token is None: return Classification(MemeClassification.UNKNOWN,"Codex has no token metadata","codex")
        if token.address in self.stock_addresses: return Classification(MemeClassification.NOT_MEME,"contract is an official Robinhood Stock Token","local-assets")
        categories=set(token.categories)
        if "memes" in categories or "meme" in categories: return Classification(MemeClassification.MEME,"Codex category includes memes","codex-category")
        if categories & {"stablecoins","stablecoin","wrapped-assets","layer-1","l1","defi"}: return Classification(MemeClassification.NOT_MEME,"Codex category identifies non-meme asset","codex-category")
        return Classification(MemeClassification.UNKNOWN,"insufficient authoritative category metadata","codex")
