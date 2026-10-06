from pathlib import Path

import pytest

from zbx_sender_service import (
    HistoryStore,
    MetricRequest,
    SendResult,
    build_command,
    build_timestamp_payload,
    command_preview,
    normalize_numeric,
    parse_timestamp,
    send_metric,
    validate_request,
)


def valid_request(**overrides):
    data = {
        "server": "zabbix.local",
        "port": 10051,
        "host": "api-prod-01",
        "key": "api.health",
        "value": "1",
        "value_type": "numeric",
        "timestamp": None,
        "timeout": 10,
    }
    data.update(overrides)
    return MetricRequest(**data)


def test_build_command_without_timestamp_is_shell_free():
    request = valid_request(value="1,50")
    assert build_command(request) == [
        "zabbix_sender",
        "-z",
        "zabbix.local",
        "-p",
        "10051",
        "-s",
        "api-prod-01",
        "-k",
        "api.health",
        "-o",
        "1.5",
    ]


def test_timestamp_payload_uses_zabbix_sender_input_format():
    request = valid_request(value="ok", value_type="text", timestamp=1735689600)
    assert build_timestamp_payload(request) == '"api-prod-01" api.health 1735689600 "ok"\n'


def test_timestamp_command_requires_input_path():
    request = valid_request(timestamp=1735689600)
    with pytest.raises(ValueError):
        build_command(request)
    assert build_command(request, input_file="payload.txt")[-2:] == ["-i", "payload.txt"]


def test_normalize_numeric_accepts_brazilian_decimal_separator():
    assert normalize_numeric("1,5000") == "1.5"
    assert normalize_numeric("0") == "0"


def test_invalid_numeric_is_reported():
    errors = validate_request(valid_request(value="abc"))
    assert "Informe um valor numérico válido." in errors


def test_parse_timestamp_supports_epoch_and_iso():
    assert parse_timestamp("1735689600") == 1735689600
    assert parse_timestamp("2025-01-01 00:00:00") == 1735689600
    assert parse_timestamp("") is None


def test_invalid_timestamp_is_rejected():
    with pytest.raises(ValueError, match="Use timestamp"):
        parse_timestamp("ontem")


def test_command_preview_is_readable():
    preview = command_preview(valid_request())
    assert preview.startswith("zabbix_sender -z zabbix.local -p 10051")
    assert "-k api.health -o 1" in preview


def test_history_store_recovers_and_limits_records(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.json")
    request = valid_request()
    result = SendResult(True, "Enviado com sucesso", "sent: 1; skipped: 0; total: 1")

    for _ in range(35):
        store.append(request, result)

    entries = store.load()
    assert len(entries) == 30
    assert entries[0]["success"] is True
    store.clear()
    assert store.load() == []


def test_send_metric_executes_sender_without_shell(tmp_path: Path):
    fake_sender = tmp_path / "zabbix_sender"
    fake_sender.write_text(
        "#!/bin/sh\nprintf 'sent: 1; skipped: 0; total: 1\\n'\n",
        encoding="utf-8",
    )
    fake_sender.chmod(0o755)

    result = send_metric(valid_request(), str(fake_sender))

    assert result.success is True
    assert result.message == "Enviado com sucesso"
    assert "sent: 1" in result.output
