import asyncio
import importlib.util
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "zbx-report.py"
MODULE_SPEC = importlib.util.spec_from_file_location("zbx_report", SCRIPT_PATH)
zbx_report = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(zbx_report)


class ServiceTests(unittest.TestCase):
    def test_load_settings_uses_previous_day_and_environment_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.ini"
            config_path.write_text(
                """
[GERAL]
ZABBIX_URL = https://zabbix.example/zabbix
USERNAME = env:ZABBIX_USERNAME
PASSWORD = env:ZABBIX_PASSWORD
PERIOD_MODE = previous_day
OUTPUT_DIR = reports
LOG_DIR = logs
MAX_ATTEMPTS = 4
RETRY_DELAY_SECONDS = 0
RETRY_BACKOFF = 2

[CONJUNTO]
pagina = SERVIDORES
TEMPLATE_NAME = Template
TRIGGER_NAME = Trigger
TEMPLATE_GROUP_NAME = Templates
HOSTGROUP_NAME = Hosts
""".strip(),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {"ZABBIX_USERNAME": "user", "ZABBIX_PASSWORD": "secret"},
                clear=False,
            ):
                settings = zbx_report.load_settings(config_path)

        self.assertEqual(settings.username, "user")
        self.assertEqual(settings.password, "secret")
        self.assertEqual(settings.from_time[-8:], "00:00:00")
        self.assertEqual(settings.to_time[-8:], "23:59:59")
        self.assertEqual(settings.max_attempts, 4)
        self.assertEqual(list(settings.filters), ["SERVIDORES"])

    def test_run_with_retries_succeeds_after_transient_failures(self):
        settings = zbx_report.Settings(
            zabbix_url="https://zabbix.example/zabbix",
            username="user",
            password="secret",
            from_time="2026-09-16 00:00:00",
            to_time="2026-09-16 23:59:59",
            filters={},
            output_dir=Path("reports"),
            log_dir=Path("logs"),
            max_attempts=3,
            retry_delay_seconds=0,
            retry_backoff=2,
            log_level="INFO",
        )
        logger = logging.getLogger("test_zabbix_report")
        calls = 0

        async def fake_run_once(_settings, _logger):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("falha temporária")
            return Path("reports/report.xlsx")

        with patch.object(zbx_report, "run_once", side_effect=fake_run_once):
            result = asyncio.run(zbx_report.run_with_retries(settings, logger))

        self.assertEqual(result, 0)
        self.assertEqual(calls, 3)

    def test_run_with_retries_returns_failure_after_last_attempt(self):
        settings = zbx_report.Settings(
            zabbix_url="https://zabbix.example/zabbix",
            username="user",
            password="secret",
            from_time="2026-09-16 00:00:00",
            to_time="2026-09-16 23:59:59",
            filters={},
            output_dir=Path("reports"),
            log_dir=Path("logs"),
            max_attempts=2,
            retry_delay_seconds=0,
            retry_backoff=2,
            log_level="INFO",
        )
        logger = logging.getLogger("test_zabbix_report_failure")

        async def always_fail(_settings, _logger):
            raise RuntimeError("falha permanente")

        with patch.object(zbx_report, "run_once", side_effect=always_fail):
            result = asyncio.run(zbx_report.run_with_retries(settings, logger))

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
