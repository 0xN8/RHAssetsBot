"""SQLite persistence for discovered assets and alert delivery state."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Asset


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS assets (
                asset_id TEXT PRIMARY KEY,
                token_symbol TEXT,
                name TEXT,
                contract_address TEXT,
                status TEXT,
                multiplier TEXT,
                trading_capabilities TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                alert_sent_at TEXT,
                alert_attempts INTEGER NOT NULL DEFAULT 0,
                last_alert_error TEXT,
                alert_state TEXT NOT NULL DEFAULT 'pending'
            )"""
        )
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(assets)")}
        if "alert_state" not in columns:
            self.connection.execute("ALTER TABLE assets ADD COLUMN alert_state TEXT NOT NULL DEFAULT 'pending'")
        self.connection.execute("CREATE TABLE IF NOT EXISTS monitor_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS meme_tokens (
          network_id INTEGER NOT NULL, token_address TEXT NOT NULL, symbol TEXT, name TEXT, token_created_at INTEGER,
          first_seen_at TEXT NOT NULL, classification TEXT NOT NULL, classification_reason TEXT, classification_source TEXT,
          classified_at TEXT NOT NULL, total_supply REAL, current_price_usd REAL, current_market_cap REAL,
          current_liquidity_usd REAL, ath_price_usd REAL, ath_market_cap REAL, ath_timestamp INTEGER,
          ath_last_scanned_at TEXT, ath_scanned_through_timestamp INTEGER, primary_pair_address TEXT, raw_json TEXT NOT NULL,
          last_updated_at TEXT NOT NULL, PRIMARY KEY(network_id, token_address));
        CREATE TABLE IF NOT EXISTS stock_token_meme_associations (
          stock_asset_id TEXT NOT NULL, meme_network_id INTEGER NOT NULL, meme_token_address TEXT NOT NULL,
          first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          PRIMARY KEY(stock_asset_id,meme_network_id,meme_token_address), FOREIGN KEY(stock_asset_id) REFERENCES assets(asset_id));
        CREATE TABLE IF NOT EXISTS meme_pools (
          network_id INTEGER NOT NULL, pair_address TEXT NOT NULL, pair_id TEXT, stock_asset_id TEXT NOT NULL,
          meme_token_address TEXT NOT NULL, token0_address TEXT NOT NULL, token1_address TEXT NOT NULL, protocol TEXT,
          exchange_id TEXT, fee INTEGER, created_at INTEGER, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
          liquidity_usd REAL, volume_usd REAL, is_primary_pair INTEGER NOT NULL DEFAULT 0, raw_json TEXT NOT NULL,
          PRIMARY KEY(network_id,pair_address));
        CREATE TABLE IF NOT EXISTS meme_candidates (
          network_id INTEGER NOT NULL, token_address TEXT NOT NULL, stock_asset_id TEXT NOT NULL, first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL, classification TEXT NOT NULL, reason TEXT, raw_json TEXT NOT NULL,
          PRIMARY KEY(network_id,token_address,stock_asset_id));
        CREATE TABLE IF NOT EXISTS meme_alerts (
          stock_asset_id TEXT NOT NULL, meme_network_id INTEGER NOT NULL, meme_token_address TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, sent_at TEXT, last_error TEXT,
          PRIMARY KEY(stock_asset_id,meme_network_id,meme_token_address));
        CREATE INDEX IF NOT EXISTS idx_meme_pools_meme ON meme_pools(network_id,meme_token_address);
        """)
        self.connection.commit()

    def baseline_initialized(self) -> bool:
        return self.connection.execute("SELECT 1 FROM monitor_state WHERE key = 'baseline_initialized'").fetchone() is not None

    def mark_baseline_initialized(self) -> None:
        self.connection.execute("INSERT OR REPLACE INTO monitor_state (key, value) VALUES ('baseline_initialized', ?)", (utc_now(),))
        self.connection.commit()

    def has_asset(self, asset_id: str) -> bool:
        return self.connection.execute("SELECT 1 FROM assets WHERE asset_id = ?", (asset_id,)).fetchone() is not None

    def insert_asset(self, asset: Asset, alert_state: str = "pending") -> None:
        now = utc_now()
        self.connection.execute(
            """INSERT OR IGNORE INTO assets
               (asset_id, token_symbol, name, contract_address, status, multiplier, trading_capabilities,
                first_seen_at, last_seen_at, raw_json, alert_state)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (*self._asset_values(asset, now, now), alert_state),
        )
        self.connection.commit()

    def update_asset(self, asset: Asset) -> list[str]:
        row = self.connection.execute("SELECT * FROM assets WHERE asset_id = ?", (asset.asset_id,)).fetchone()
        if row is None:
            raise KeyError(asset.asset_id)
        current = self._metadata(asset)
        prior = {key: row[key] for key in current}
        changes = [key for key, value in current.items() if prior[key] != value]
        self.connection.execute(
            """UPDATE assets SET token_symbol=?, name=?, contract_address=?, status=?, multiplier=?,
               trading_capabilities=?, last_seen_at=?, raw_json=? WHERE asset_id=?""",
            (*current.values(), utc_now(), json.dumps(asset.raw, sort_keys=True), asset.asset_id),
        )
        self.connection.commit()
        return changes

    def pending_alerts(self) -> list[Asset]:
        rows = self.connection.execute("SELECT raw_json FROM assets WHERE alert_state = 'pending' ORDER BY first_seen_at, asset_id").fetchall()
        return [Asset.from_api(json.loads(row["raw_json"])) for row in rows]

    def record_alert_attempt(self, asset_id: str) -> None:
        self.connection.execute(
            "UPDATE assets SET alert_attempts = alert_attempts + 1, last_alert_error = ? WHERE asset_id = ?",
            (None, asset_id),
        )
        self.connection.commit()

    def record_alert_error(self, asset_id: str, error: str) -> None:
        self.connection.execute("UPDATE assets SET last_alert_error = ? WHERE asset_id = ?", (error, asset_id))
        self.connection.commit()

    def mark_alert_sent(self, asset_id: str) -> None:
        self.connection.execute(
            "UPDATE assets SET alert_sent_at = ?, last_alert_error = NULL, alert_state = 'sent' WHERE asset_id = ?", (utc_now(), asset_id)
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    # Codex/memecoin service layer. The existing assets table remains the authoritative Stock Token registry.
    def stock_tokens(self) -> list[sqlite3.Row]:
        return self.connection.execute("SELECT asset_id, token_symbol, name, contract_address, first_seen_at FROM assets").fetchall()

    def upsert_candidate(self, stock_id: str, network: int, address: str, classification: str, reason: str, raw: dict) -> None:
        now=utc_now(); self.connection.execute("""INSERT INTO meme_candidates VALUES(?,?,?,?,?,?,?,?)
          ON CONFLICT(network_id,token_address,stock_asset_id) DO UPDATE SET last_seen_at=excluded.last_seen_at,classification=excluded.classification,reason=excluded.reason,raw_json=excluded.raw_json""",(network,address,stock_id,now,now,classification,reason,json.dumps(raw,sort_keys=True))); self.connection.commit()

    def persist_meme(self, stock_id: str, token, pair) -> bool:
        """Persist one confirmed association and pool. Returns true only for a new association."""
        now=utc_now(); exists=self.connection.execute("SELECT 1 FROM stock_token_meme_associations WHERE stock_asset_id=? AND meme_network_id=? AND meme_token_address=?",(stock_id,token.network_id,token.address)).fetchone() is not None
        self.connection.execute("""INSERT INTO meme_tokens(network_id,token_address,symbol,name,token_created_at,first_seen_at,classification,classification_reason,classification_source,classified_at,total_supply,raw_json,last_updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(network_id,token_address) DO UPDATE SET symbol=excluded.symbol,name=excluded.name,total_supply=excluded.total_supply,raw_json=excluded.raw_json,last_updated_at=excluded.last_updated_at""",(token.network_id,token.address,token.symbol,token.name,token.created_at,now,"MEME","Codex category includes memes","codex-category",now,token.total_supply,json.dumps(token.raw or {},sort_keys=True),now))
        self.connection.execute("""INSERT INTO stock_token_meme_associations VALUES(?,?,?,?,?) ON CONFLICT(stock_asset_id,meme_network_id,meme_token_address) DO UPDATE SET last_seen_at=excluded.last_seen_at""",(stock_id,token.network_id,token.address,now,now))
        self.connection.execute("""INSERT INTO meme_pools(network_id,pair_address,pair_id,stock_asset_id,meme_token_address,token0_address,token1_address,protocol,exchange_id,fee,created_at,first_seen_at,last_seen_at,liquidity_usd,volume_usd,raw_json)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(network_id,pair_address) DO UPDATE SET liquidity_usd=excluded.liquidity_usd,volume_usd=excluded.volume_usd,last_seen_at=excluded.last_seen_at,raw_json=excluded.raw_json""",(pair.network_id,pair.address,pair.pair_id,stock_id,token.address,pair.token0,pair.token1,pair.protocol,pair.exchange_id,pair.fee,pair.created_at,now,now,pair.liquidity_usd,pair.volume_usd,json.dumps(pair.raw or {},sort_keys=True)))
        if not exists: self.connection.execute("INSERT OR IGNORE INTO meme_alerts(stock_asset_id,meme_network_id,meme_token_address) VALUES(?,?,?)",(stock_id,token.network_id,token.address))
        self.connection.commit(); self.refresh_primary_pair(token.network_id,token.address); return not exists

    def refresh_primary_pair(self, network: int, address: str) -> None:
        row=self.connection.execute("SELECT pair_address FROM meme_pools WHERE network_id=? AND meme_token_address=? ORDER BY COALESCE(liquidity_usd,0) DESC,pair_address LIMIT 1",(network,address)).fetchone(); primary=row[0] if row else None
        self.connection.execute("UPDATE meme_pools SET is_primary_pair=CASE WHEN pair_address=? THEN 1 ELSE 0 END WHERE network_id=? AND meme_token_address=?",(primary,network,address)); self.connection.execute("UPDATE meme_tokens SET primary_pair_address=?,last_updated_at=? WHERE network_id=? AND token_address=?",(primary,utc_now(),network,address)); self.connection.commit()

    def update_ath(self, network:int,address:str, price:float|None,timestamp:int|None, scanned_through:int) -> None:
        row=self.connection.execute("SELECT ath_price_usd,ath_timestamp,total_supply FROM meme_tokens WHERE network_id=? AND token_address=?",(network,address)).fetchone()
        if row is None:return
        old=row["ath_price_usd"]; replace=price is not None and (old is None or price>old or (price==old and timestamp is not None and (row["ath_timestamp"] is None or timestamp<row["ath_timestamp"])))
        chosen_price,chosen_time=(price,timestamp) if replace else (old,row["ath_timestamp"]); mc=chosen_price*row["total_supply"] if chosen_price is not None and row["total_supply"] else None
        self.connection.execute("UPDATE meme_tokens SET ath_price_usd=?,ath_timestamp=?,ath_market_cap=?,ath_last_scanned_at=?,ath_scanned_through_timestamp=? WHERE network_id=? AND token_address=?",(chosen_price,chosen_time,mc,utc_now(),scanned_through,network,address)); self.connection.commit()

    def update_current_meme(self, network:int,address:str,price:float|None,liquidity:float|None) -> None:
        row=self.get_meme_metrics(address,network)
        if not row:return
        market_cap=price*row["total_supply"] if price is not None and row["total_supply"] else None
        self.connection.execute("UPDATE meme_tokens SET current_price_usd=?,current_market_cap=?,current_liquidity_usd=?,last_updated_at=? WHERE network_id=? AND token_address=?",(price,market_cap,liquidity,utc_now(),network,address));self.connection.commit()

    def pending_meme_alerts(self):
        return self.connection.execute("""SELECT a.stock_asset_id,a.meme_network_id,a.meme_token_address,s.token_symbol,m.*,p.pair_address,p.protocol,p.created_at
        FROM meme_alerts a JOIN meme_tokens m ON m.network_id=a.meme_network_id AND m.token_address=a.meme_token_address
        JOIN assets s ON s.asset_id=a.stock_asset_id LEFT JOIN meme_pools p ON p.network_id=m.network_id AND p.pair_address=m.primary_pair_address
        WHERE a.state='pending'""").fetchall()
    def meme_alert_attempt(self, stock:str,network:int,address:str,error:str|None=None) -> None:
        if error is None:self.connection.execute("UPDATE meme_alerts SET attempts=attempts+1 WHERE stock_asset_id=? AND meme_network_id=? AND meme_token_address=?",(stock,network,address))
        else:self.connection.execute("UPDATE meme_alerts SET last_error=? WHERE stock_asset_id=? AND meme_network_id=? AND meme_token_address=?",(error,stock,network,address))
        self.connection.commit()
    def mark_meme_alert_sent(self,stock:str,network:int,address:str)->None:
        self.connection.execute("UPDATE meme_alerts SET state='sent',sent_at=?,last_error=NULL WHERE stock_asset_id=? AND meme_network_id=? AND meme_token_address=?",(utc_now(),stock,network,address));self.connection.commit()

    def get_memes_for_stock_token(self, stock_id: str) -> list[sqlite3.Row]:
        return self.connection.execute("SELECT m.* FROM meme_tokens m JOIN stock_token_meme_associations a ON a.meme_network_id=m.network_id AND a.meme_token_address=m.token_address WHERE a.stock_asset_id=?",(stock_id,)).fetchall()
    def get_pools_for_meme(self,address:str,network:int=4663)->list[sqlite3.Row]: return self.connection.execute("SELECT * FROM meme_pools WHERE network_id=? AND meme_token_address=?",(network,address)).fetchall()
    def get_meme_metrics(self,address:str,network:int=4663): return self.connection.execute("SELECT * FROM meme_tokens WHERE network_id=? AND token_address=?",(network,address)).fetchone()

    @staticmethod
    def _metadata(asset: Asset) -> dict[str, str | None]:
        return {
            "token_symbol": asset.token_symbol,
            "name": asset.name,
            "contract_address": ",".join(asset.contract_addresses) or None,
            "status": asset.status,
            "multiplier": asset.multiplier,
            "trading_capabilities": json.dumps(asset.trading_capabilities, sort_keys=True),
        }

    def _asset_values(self, asset: Asset, first_seen: str, last_seen: str) -> tuple[object, ...]:
        metadata = self._metadata(asset)
        return (
            asset.asset_id, *metadata.values(), first_seen, last_seen, json.dumps(asset.raw, sort_keys=True)
        )
