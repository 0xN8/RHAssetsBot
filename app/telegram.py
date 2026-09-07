"""Telegram alert delivery."""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from .models import Asset


class TelegramClient:
    def __init__(self, token: str, chat_id: str, session: requests.Session | None = None) -> None:
        self.token = token
        self.chat_id = chat_id
        self.session = session or requests.Session()

    def send_asset_alert(self, asset: Asset) -> None:
        self._send(format_asset_alert(asset))

    def send_status_alert(self, message: str) -> None:
        self._send(f"✅ ROBINHOOD STOCK TOKEN MONITOR\n\n{message}\nAt: {utc_timestamp()}")

    def send_metadata_change_alert(self, asset: Asset, changed_fields: set[str]) -> None:
        lines = ["ℹ️ ROBINHOOD STOCK TOKEN METADATA CHANGED", "", f"Ticker / Token Symbol: {asset.token_symbol or 'Unknown'}",
                 f"Name: {asset.name or 'Unknown'}", f"Robinhood Asset ID: {asset.asset_id}",
                 f"Changed: {', '.join(sorted(changed_fields))}"]
        if asset.status:
            lines.append(f"Status: {asset.status}")
        if asset.multiplier:
            lines.append(f"Multiplier: {asset.multiplier}")
        lines.append(f"Detected At: {utc_timestamp()}")
        self._send("\n".join(lines))

    def _send(self, text: str) -> None:
        response = self.session.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                                     json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}, timeout=(5, 20))
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("ok") is not True:
            raise RuntimeError("Telegram API did not confirm delivery")

    def send_meme_alert(self, stock, meme, pair, metrics) -> None:
        get=lambda x: meme[x] if hasattr(meme,"keys") else getattr(meme,x)
        lines=["🚨 NEW STOCK-TOKEN MEMECOIN","",f"Stock Token: {stock['token_symbol'] or stock['asset_id']}",f"Meme: {get('name') or 'Unknown'} ({get('symbol') or '?'})",f"Meme Contract: {get('token_address') if hasattr(meme,'keys') else get('address')}",f"Pool: {pair['pair_address'] if hasattr(pair,'keys') else pair.address}"]
        protocol=pair['protocol'] if hasattr(pair,'keys') else pair.protocol; created=pair['created_at'] if hasattr(pair,'keys') else pair.created_at
        if protocol: lines.append(f"DEX/Protocol: {protocol}")
        if created: lines.append(f"Pair Created: {datetime.fromtimestamp(created,timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
        if metrics and metrics["current_market_cap"]: lines.append(f"Current Market Cap: ${metrics['current_market_cap']:,.0f}")
        if metrics and metrics["ath_market_cap"]: lines.append(f"ATH Market Cap: ${metrics['ath_market_cap']:,.0f}")
        response=self.session.post(f"https://api.telegram.org/bot{self.token}/sendMessage",json={"chat_id":self.chat_id,"text":"\n".join(lines)},timeout=(5,20)); response.raise_for_status()


def format_asset_alert(asset: Asset, detected_at: datetime | None = None) -> str:
    detected_at = detected_at or datetime.now(timezone.utc)
    lines = ["🚨 NEW ROBINHOOD STOCK TOKEN", ""]
    if asset.token_symbol:
        lines.append(f"Ticker / Token Symbol: {asset.token_symbol}")
    if asset.name:
        lines.append(f"Name: {asset.name}")
    lines.append(f"Robinhood Asset ID: {asset.asset_id}")
    if asset.contract_addresses:
        lines.append("Contract Address(es):")
        lines.extend(f"- {address}" for address in asset.contract_addresses)
    if asset.status:
        lines.append(f"Status: {asset.status}")
    if asset.multiplier:
        lines.append(f"Multiplier: {asset.multiplier}")
    lines.append(f"Detected At: {detected_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    return "\n".join(lines)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
