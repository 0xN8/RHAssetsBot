"""Incremental ATH calculation from pool OHLCV. Candles are not retained."""
from __future__ import annotations
import time
from .codex_models import CodexPair

def metrics(current_market_cap: float | None, ath_market_cap: float | None, ath_timestamp: int | None, now: int | None = None) -> dict[str,float|None]:
    now=now or int(time.time()); result={"days_since_ath":None,"drawdown_from_ath":None,"return_multiple_to_ath":None}
    if ath_timestamp is not None: result["days_since_ath"]=(now-ath_timestamp)/86400
    if ath_market_cap and ath_market_cap>0 and current_market_cap is not None:
        result["drawdown_from_ath"]=current_market_cap/ath_market_cap-1
        result["return_multiple_to_ath"]=ath_market_cap/current_market_cap if current_market_cap>0 else None
    return result

class AthScanner:
    def __init__(self, codex, database, resolution: str="60") -> None: self.codex,self.database,self.resolution=codex,database,resolution
    def scan(self, network: int, address: str, pair: CodexPair, start: int | None = None, now: int | None = None) -> None:
        now=now or int(time.time()); row=self.database.get_meme_metrics(address,network); start=start if start is not None else (row["ath_scanned_through_timestamp"] or pair.created_at or 0)
        # At one-hour resolution, 1,500 bars span 62.5 days. Walk windows, never silently truncate.
        seconds={"15":900,"60":3600,"240":14400,"1D":86400}.get(self.resolution,3600); window=seconds*1500
        best_price,best_time=None,None
        for left in range(start,now+1,window):
            right=min(left+window,now)
            for timestamp,high in self.codex.bars(pair,left,right,self.resolution):
                if best_price is None or high>best_price or (high==best_price and timestamp<best_time): best_price,best_time=high,timestamp
        self.database.update_ath(network,address,best_price,best_time,now)
