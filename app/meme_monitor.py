"""Independent Codex worker; failures never affect Robinhood polling."""
from __future__ import annotations
import logging,time
from .ath import AthScanner
from .classifier import MemeClassifier
from .codex import CodexRateLimited
from .codex_models import MemeClassification, normalize_address
LOG=logging.getLogger(__name__)

class CodexMemeWorker:
    def __init__(self,database,codex,telegram=None,network_id:int=4663,new_window_hours:float=24,ath_resolution:str="60"):
        self.database,self.codex,self.telegram,self.network_id=database,codex,telegram,network_id; self.new_window_hours=new_window_hours; self.ath=AthScanner(codex,database,ath_resolution); self.last={}
    def due(self,stock,now:int,new_interval:float,old_interval:float)->bool:
        age=now-time.mktime(time.strptime(stock["first_seen_at"],"%Y-%m-%dT%H:%M:%SZ")); interval=new_interval if age<self.new_window_hours*3600 else old_interval
        return now-self.last.get(stock["asset_id"],0)>=interval
    def run_due(self,new_interval:float=15,old_interval:float=600)->None:
        now=int(time.time())
        for stock in self.database.stock_tokens():
            if self.due(stock,now,new_interval,old_interval):
                try:self.scan_stock(stock,now)
                except CodexRateLimited as e: LOG.warning("Codex rate limited; retry after %ss",e.retry_after); return
                except Exception as e: LOG.exception("Codex scan failed for %s: %s",stock["asset_id"],e)
    def scan_stock(self,stock,now:int|None=None)->None:
        now=now or int(time.time()); addresses=[normalize_address(a) for a in (stock["contract_address"] or "").split(",") if a]
        all_stock={normalize_address(a) for s in self.database.stock_tokens() for a in (s["contract_address"] or "").split(",") if a}; classifier=MemeClassifier(all_stock)
        for stock_address in addresses:
            for pair in self.codex.pairs_for_token(stock_address,self.network_id):
                candidate=pair.token1 if pair.token0==stock_address else pair.token0 if pair.token1==stock_address else None
                if not candidate: continue
                token=self.codex.token(candidate,self.network_id); verdict=classifier.classify(token)
                if verdict.value is not MemeClassification.MEME:
                    self.database.upsert_candidate(stock["asset_id"],self.network_id,candidate,verdict.value,verdict.reason,(token.raw if token else {})); continue
                enriched=self.codex.pair_metadata(pair); is_new=self.database.persist_meme(stock["asset_id"],token,enriched)
                primary=self.database.get_meme_metrics(token.address,self.network_id)["primary_pair_address"]
                if primary==enriched.address:
                    self.ath.scan(self.network_id,token.address,enriched,now=now)
                    raw=enriched.raw or {}; side="token0" if enriched.token0==token.address else "token1"
                    try: price=float((raw.get(side) or {}).get("price"))
                    except (TypeError,ValueError): price=None
                    self.database.update_current_meme(self.network_id,token.address,price,enriched.liquidity_usd)
        self.last[stock["asset_id"]]=now
        self.deliver_pending_alerts()

    def deliver_pending_alerts(self)->None:
        if not self.telegram:return
        for row in self.database.pending_meme_alerts():
            self.database.meme_alert_attempt(row["stock_asset_id"],row["meme_network_id"],row["meme_token_address"])
            try:self.telegram.send_meme_alert(row,row,row,row)
            except Exception as e:self.database.meme_alert_attempt(row["stock_asset_id"],row["meme_network_id"],row["meme_token_address"],str(e));LOG.error("Meme alert failed: %s",e)
            else:self.database.mark_meme_alert_sent(row["stock_asset_id"],row["meme_network_id"],row["meme_token_address"])
