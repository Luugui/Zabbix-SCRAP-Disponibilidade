from pathlib import Path

import pytest

from zbx_sender_service import (
    HistoryStore,
    MetricRequest,
    SendResult,
    normalize_numeric,
    parse_timestamp,
    send_metric,
    sender_preview,
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


def test_sender_preview_describes_native_library_call():
    preview = sender_preview(valid_request())
    assert preview.startswith("Sender(server='zabbix.local', port=10051)")
    assert ".send_value('api-prod-01', 'api.health', '1')" in preview


def test_sender_preview_survives_invalid_numeric_input_during_typing():
    preview = sender_preview(valid_request(value="-"))
    assert "send_value('api-prod-01', 'api.health', '-')" in preview


class FakeResponse:
    processed = 1
    failed = 0
    total = 1
    time = 0.001


class FakeSender:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.__class__.instances.append(self)

    def send_value(self, host, key, value, clock=None):
        self.calls.append((host, key, value, clock))
        return FakeResponse()


def test_send_metric_uses_official_sender_factory_without_external_process():
    FakeSender.instances.clear()
    request = valid_request(value="1,50", timestamp=1735689600)

    result = send_metric(request, sender_factory=FakeSender)

    assert result.success is True
    assert result.message == "Enviado com sucesso"
    assert "processados: 1" in result.output
    assert len(FakeSender.instances) == 1
    instance = FakeSender.instances[0]
    assert instance.kwargs == {
        "server": "zabbix.local",
        "port": 10051,
        "timeout": 10,
    }
    assert instance.calls == [("api-prod-01", "api.health", "1.5", 1735689600)]


def test_send_metric_reports_failed_trapper_response():
    class FailedResponse:
        processed = 0
        failed = 1
        total = 1
        time = 0.002

    class FailedSender(FakeSender):
        def send_value(self, host, key, value, clock=None):
            return FailedResponse()

    result = send_metric(valid_request(), sender_factory=FailedSender)

    assert result.success is False
    assert result.returncode == 1
    assert "falhos: 1" in result.output


def test_send_metric_maps_library_exception_to_user_result():
    class BrokenSender:
        def __init__(self, **_kwargs):
            pass

        def send_value(self, *_args):
            raise OSError("connection refused")

    result = send_metric(valid_request(), sender_factory=BrokenSender)

    assert result.success is False
    assert result.message == "Não foi possível enviar a métrica ao Zabbix."
    assert "connection refused" in result.output


def test_history_store_recovers_and_limits_records(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.json")
    request = valid_request()
    result = SendResult(True, "Enviado com sucesso", "processados: 1; falhos: 0; total: 1")

    for _ in range(35):
        store.append(request, result)

    entries = store.load()
    assert len(entries) == 30
    assert entries[0]["success"] is True
    store.clear()
    assert store.load() == []
