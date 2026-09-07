"""Small HTTP GraphQL client for documented Codex queries."""
from __future__ import annotations
import logging, time
from typing import Any
import requests
from .codex_models import CodexPair, CodexToken

LOG = logging.getLogger(__name__)
URL = "https://graph.codex.io/graphql"
PAIR_QUERY = '''query Pairs($address:String!, $network:Int!, $limit:Int) { listPairsForToken(tokenAddress:$address networkId:$network limit:$limit) { address id networkId exchangeHash fee protocol token0 token1 createdAt } }'''
TOKEN_QUERY = '''query Token($address:String!, $network:Int!) { token(input:{address:$address networkId:$network}) { address networkId name symbol createdAt categories { id } info { totalSupply } } }'''
META_QUERY = '''query Meta($pairId:String!) { pairMetadata(pairId:$pairId) { id pairAddress networkId exchangeId fee liquidity volume24 createdAt token0 { address price } token1 { address price } } }'''
BARS_QUERY = '''query Bars($symbol:String!, $from:Int!, $to:Int!, $resolution:String!, $countback:Int!) { getBars(symbol:$symbol symbolType:POOL from:$from to:$to resolution:$resolution countback:$countback removeEmptyBars:true) { t h c } }'''

class CodexError(RuntimeError): pass
class CodexRateLimited(CodexError):
    def __init__(self, retry_after: float | None = None): self.retry_after = retry_after

class CodexClient:
    def __init__(self, api_key: str, session: requests.Session | None = None, pair_limit: int = 500) -> None:
        self.session, self.pair_limit, self.next_allowed_at = session or requests.Session(), pair_limit, 0.0
        self.session.headers.update({"Authorization": api_key, "Content-Type": "application/json"})
    def _query(self, query: str, variables: dict[str, Any]) -> Any:
        delay = self.next_allowed_at - time.monotonic()
        if delay > 0: time.sleep(delay)
        response = self.session.post(URL, json={"query":query,"variables":variables}, timeout=(5, 30))
        if response.status_code == 429:
            retry = float(response.headers.get("Retry-After", "5")); self.next_allowed_at = time.monotonic()+retry; raise CodexRateLimited(retry)
        response.raise_for_status(); payload = response.json()
        errors = payload.get("errors", []) if isinstance(payload, dict) else []
        if errors:
            text = "; ".join(str(e.get("message", e)) for e in errors)
            if "rate" in text.lower() or "limit" in text.lower(): self.next_allowed_at=time.monotonic()+5; raise CodexRateLimited(5)
            raise CodexError(text)
        return payload.get("data", {})
    def pairs_for_token(self, address: str, network_id: int) -> list[CodexPair]:
        result=self._query(PAIR_QUERY,{"address":address,"network":network_id,"limit":self.pair_limit}).get("listPairsForToken", [])
        if isinstance(result, dict): result=result.get("results", [])
        return [CodexPair.from_api(x) for x in result if isinstance(x, dict)]
    def token(self, address: str, network_id: int) -> CodexToken | None:
        value=self._query(TOKEN_QUERY,{"address":address,"network":network_id}).get("token")
        return CodexToken.from_api(value, network_id) if isinstance(value, dict) else None
    def pair_metadata(self, pair: CodexPair) -> CodexPair:
        value=self._query(META_QUERY,{"pairId":pair.pair_id}).get("pairMetadata")
        if not isinstance(value,dict): return pair
        merged={**pair.raw,**value,"address":value.get("pairAddress",pair.address),"id":value.get("id",pair.pair_id),"networkId":value.get("networkId",pair.network_id),"token0":(value.get("token0") or {}).get("address",pair.token0),"token1":(value.get("token1") or {}).get("address",pair.token1),"protocol":pair.protocol}
        return CodexPair.from_api(merged)
    def bars(self, pair: CodexPair, start: int, end: int, resolution: str) -> list[tuple[int,float]]:
        data=self._query(BARS_QUERY,{"symbol":f"{pair.address}:{pair.network_id}","from":start,"to":end,"resolution":resolution,"countback":1500}).get("getBars") or {}
        return [(int(t),float(h)) for t,h in zip(data.get("t",[]),data.get("h",[])) if t is not None and h is not None and float(h)>0]
