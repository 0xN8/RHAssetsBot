from __future__ import annotations
import tempfile, unittest
from pathlib import Path
from unittest.mock import Mock
from app.ath import AthScanner, metrics
from app.codex_models import CodexPair, CodexToken, MemeClassification
from app.database import Database
from app.meme_monitor import CodexMemeWorker
from app.models import Asset

STOCK="0xstock"; MEME="0xmeme"; USDG="0xusdg"; OTHER="0xother"
def stock(): return Asset.from_api({"id":"nvda","tokenSymbol":"NVDA","tokenName":"NVDA • Robinhood Token","deployments":[{"contractAddress":STOCK}]})
def pair(address:str,t0:str,t1:str,liq:float=100): return CodexPair(4663,address,f"{address}:4663",t0,t1,"UniswapV4",3000,100,liq,1,"uni",{})
def meme(address=MEME): return CodexToken(4663,address,"AI","Artificial Inu",100,1_000_000,("memes",),{"address":address})

class StubCodex:
    def __init__(self,pairs=None,tokens=None,bars=None): self.pairs=pairs or [];self.tokens=tokens or {};self.bars_value=bars or [];self.bar_calls=[]
    def pairs_for_token(self,*_): return self.pairs
    def token(self,address,*_): return self.tokens.get(address)
    def pair_metadata(self,p): return p
    def bars(self,p,start,end,res): self.bar_calls.append((start,end));return [(t,h) for t,h in self.bars_value if start<=t<=end]

class CodexExtensionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(Path(self.tmp.name)/"x.db");self.db.insert_asset(stock(),"baseline");self.db.mark_baseline_initialized()
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def worker(self,c):return CodexMemeWorker(self.db,c,None)
    def test_token0_and_token1_orientation_persist_same_meme(self):
        c=StubCodex([pair("0xp1",STOCK,MEME),pair("0xp2",MEME,STOCK)],{MEME:meme()});self.worker(c).scan_stock(self.db.stock_tokens()[0],200)
        self.assertEqual(1,len(self.db.get_memes_for_stock_token("nvda")));self.assertEqual(2,len(self.db.get_pools_for_meme(MEME)))
    def test_non_meme_and_stock_pair_are_rejected(self):
        c=StubCodex([pair("0xu",STOCK,USDG),pair("0xs",STOCK,OTHER)],{USDG:CodexToken(4663,USDG,"USDG","USDG",None,None,("stablecoins",),{}),OTHER:CodexToken(4663,OTHER,"AAPL","AAPL Token",None,None,(),{})});self.worker(c).scan_stock(self.db.stock_tokens()[0],200)
        self.assertEqual([],self.db.get_memes_for_stock_token("nvda"));self.assertEqual(2,self.db.connection.execute("SELECT count(*) FROM meme_candidates").fetchone()[0])
    def test_unknown_can_later_become_meme(self):
        c=StubCodex([pair("0xp",STOCK,MEME)],{MEME:CodexToken(4663,MEME,"AI","AI",None,None,(),{})});w=self.worker(c);w.scan_stock(self.db.stock_tokens()[0],200);self.assertEqual(0,len(self.db.get_memes_for_stock_token("nvda")))
        c.tokens[MEME]=meme();w.scan_stock(self.db.stock_tokens()[0],201);self.assertEqual(1,len(self.db.get_memes_for_stock_token("nvda")))
    def test_primary_pair_is_highest_liquidity_and_can_change(self):
        c=StubCodex([pair("0xa",STOCK,MEME,10),pair("0xb",STOCK,MEME,20)],{MEME:meme()});w=self.worker(c);w.scan_stock(self.db.stock_tokens()[0],200);self.assertEqual("0xb",self.db.get_meme_metrics(MEME)["primary_pair_address"])
        c.pairs=[pair("0xa",STOCK,MEME,30),pair("0xb",STOCK,MEME,20)];w.scan_stock(self.db.stock_tokens()[0],201);self.assertEqual("0xa",self.db.get_meme_metrics(MEME)["primary_pair_address"])
    def test_duplicate_scan_is_idempotent(self):
        c=StubCodex([pair("0xp",STOCK,MEME)],{MEME:meme()});w=self.worker(c);w.scan_stock(self.db.stock_tokens()[0],200);w.scan_stock(self.db.stock_tokens()[0],201)
        self.assertEqual(1,self.db.connection.execute("SELECT count(*) FROM stock_token_meme_associations").fetchone()[0])
    def test_ath_and_derived_metrics(self):
        p=pair("0xp",STOCK,MEME);self.db.persist_meme("nvda",meme(),p);c=StubCodex(bars=[(100,2),(200,5),(300,5),(400,4)]);AthScanner(c,self.db).scan(4663,MEME,p,0,500)
        row=self.db.get_meme_metrics(MEME);self.assertEqual((5.0,200,5_000_000.0),(row["ath_price_usd"],row["ath_timestamp"],row["ath_market_cap"]))
        self.assertEqual(3.0,metrics(1_250_000,5_000_000,200,259400)["days_since_ath"]);self.assertEqual(-.75,metrics(1_250_000,5_000_000,200,259400)["drawdown_from_ath"]);self.assertEqual(4.0,metrics(1_250_000,5_000_000,200,259400)["return_multiple_to_ath"])
    def test_incremental_ath_replaces_only_with_new_high(self):
        p=pair("0xp",STOCK,MEME);self.db.persist_meme("nvda",meme(),p);c=StubCodex(bars=[(100,2),(200,5)]);scanner=AthScanner(c,self.db);scanner.scan(4663,MEME,p,0,250);c.bars_value=[(300,7)];scanner.scan(4663,MEME,p,251,350)
        row=self.db.get_meme_metrics(MEME);self.assertEqual((7.0,300), (row["ath_price_usd"],row["ath_timestamp"]));self.assertEqual((251,350),c.bar_calls[-1])
    def test_zero_market_cap_is_safe(self): self.assertIsNone(metrics(0,100,1,100)["return_multiple_to_ath"])
