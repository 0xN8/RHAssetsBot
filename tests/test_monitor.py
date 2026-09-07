from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import requests

from app.database import Database
from app.config import Config
from app.main import Monitor, _send_status_alert
from app.models import Asset
from app.robinhood import _extract_assets


def asset(asset_id: str, symbol: str = "ABC", **overrides: object) -> Asset:
    raw = {
        "id": asset_id,
        "tokenSymbol": symbol,
        "tokenName": f"{symbol} • Robinhood Token",
        "deployments": [{"contractAddress": "0xabc", "chainId": 4663}],
        "status": "ASSET_STATUS_ACTIVE",
        "currentMultiplier": "1.0",
        "tradingCapabilities": {"market": {"whole": "TRADING_STATUS_TRADABLE"}},
    }
    raw.update(overrides)
    return Asset.from_api(raw)


class StubRobinhood:
    def __init__(self, assets: list[Asset] | None = None, error: Exception | None = None) -> None:
        self.assets, self.error = assets or [], error

    def fetch_assets(self) -> list[Asset]:
        if self.error:
            raise self.error
        return self.assets


class StubTelegram:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.sent, self.statuses, self.metadata_changes = fail, [], [], []

    def send_asset_alert(self, value: Asset) -> None:
        if self.fail:
            raise requests.ConnectionError("Telegram unavailable")
        self.sent.append(value.asset_id)

    def send_status_alert(self, message: str) -> None:
        if self.fail:
            raise requests.ConnectionError("Telegram unavailable")
        self.statuses.append(message)

    def send_metadata_change_alert(self, value: Asset, fields: set[str]) -> None:
        if self.fail:
            raise requests.ConnectionError("Telegram unavailable")
        self.metadata_changes.append((value.asset_id, fields))


class MonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.tempdir.name) / "state.db")
        self.robinhood = StubRobinhood()
        self.telegram = StubTelegram()
        self.monitor = Monitor(self.database, self.robinhood, self.telegram)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self.database.close()
        self.tempdir.cleanup()

    def poll(self, values: list[Asset]) -> None:
        self.robinhood.assets = values
        self.monitor.poll_once()

    def test_first_startup_creates_baseline_without_alerts(self) -> None:
        self.poll([asset("1"), asset("2", "DEF")])
        self.assertTrue(self.database.baseline_initialized())
        self.assertTrue(self.database.has_asset("1"))
        self.assertEqual([], self.telegram.sent)

    def test_existing_assets_do_not_trigger_alerts(self) -> None:
        values = [asset("1")]
        self.poll(values)
        self.poll(values)
        self.assertEqual([], self.telegram.sent)

    def test_one_new_asset_triggers_exactly_one_alert(self) -> None:
        self.poll([asset("1")])
        self.poll([asset("1"), asset("2", "NEW")])
        self.assertEqual(["2"], self.telegram.sent)

    def test_multiple_new_assets_trigger_correct_alerts(self) -> None:
        self.poll([asset("1")])
        self.poll([asset("1"), asset("2", "DEF"), asset("3", "GHI")])
        self.assertEqual(["2", "3"], self.telegram.sent)

    def test_restart_does_not_realert_discovered_asset(self) -> None:
        self.poll([asset("1")])
        self.poll([asset("1"), asset("2")])
        restarted = Monitor(self.database, self.robinhood, self.telegram)  # type: ignore[arg-type]
        restarted.poll_once()
        self.assertEqual(["2"], self.telegram.sent)

    def test_api_failure_preserves_state_and_is_raised_for_loop_to_retry(self) -> None:
        self.poll([asset("1")])
        self.robinhood.error = requests.Timeout("upstream timeout")
        with self.assertRaises(requests.Timeout):
            self.monitor.poll_once()
        self.assertTrue(self.database.has_asset("1"))

    def test_telegram_failure_persists_discovery_without_duplicate_discovery(self) -> None:
        self.poll([asset("1")])
        self.telegram.fail = True
        self.poll([asset("1"), asset("2")])
        self.assertTrue(self.database.has_asset("2"))
        self.telegram.fail = False
        self.poll([asset("1"), asset("2")])
        self.assertEqual(["2"], self.telegram.sent)

    def test_metadata_change_sends_its_own_alert_without_new_asset_alert(self) -> None:
        self.poll([asset("1")])
        self.poll([asset("1", status="ASSET_STATUS_INACTIVE", currentMultiplier="2.0")])
        self.assertEqual([], self.telegram.sent)
        self.assertEqual([("1", {"status", "multiplier"})], self.telegram.metadata_changes)
        row = self.database.connection.execute("SELECT status, multiplier FROM assets WHERE asset_id = '1'").fetchone()
        self.assertEqual(("ASSET_STATUS_INACTIVE", "2.0"), tuple(row))

    def test_unknown_api_fields_do_not_break_parsing(self) -> None:
        parsed = asset("1", futureField={"nested": [1, 2]})
        self.assertEqual("1", parsed.asset_id)
        self.assertEqual([parsed.raw], _extract_assets({"assets": [parsed.raw]}))

    def test_operational_status_alert_is_safe_when_telegram_fails(self) -> None:
        self.telegram.fail = True
        _send_status_alert(self.telegram, "Monitor started")
        self.assertEqual([], self.telegram.statuses)

    def test_operational_status_alert_is_sent(self) -> None:
        _send_status_alert(self.telegram, "Monitor started")
        self.assertEqual(["Monitor started"], self.telegram.statuses)


class ConfigTests(unittest.TestCase):
    def test_from_env_loads_dotenv_file(self) -> None:
        values = {
            "TELEGRAM_BOT_TOKEN": "dotenv-token",
            "TELEGRAM_CHAT_ID": "dotenv-chat",
            "POLL_INTERVAL_SECONDS": "12",
            "DATABASE_PATH": "./dotenv.db",
        }
        with patch.dict("os.environ", {}, clear=True), patch("app.config.load_dotenv") as load_dotenv:
            with patch.dict("os.environ", values):
                config = Config.from_env()

        load_dotenv.assert_called_once_with()
        self.assertEqual("dotenv-token", config.telegram_bot_token)
        self.assertEqual("dotenv-chat", config.telegram_chat_id)
        self.assertEqual(12.0, config.poll_interval_seconds)
        self.assertEqual(Path("dotenv.db"), config.database_path)
