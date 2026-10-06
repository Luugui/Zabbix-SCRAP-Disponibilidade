"""Core services for the ZBX Sender desktop application.

Transport is implemented by the official ``zabbix_utils`` package. The GUI
therefore speaks the Zabbix Sender protocol directly and does not require the
external ``zabbix_sender`` executable.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from zabbix_utils import Sender
except ImportError:  # pragma: no cover - exercised when dependencies are absent.
    Sender = None  # type: ignore[assignment,misc]


APP_NAME = "ZBX Sender"
DEFAULT_PORT = 10051
DEFAULT_TIMEOUT = 10
MAX_HISTORY_ITEMS = 30
SENDER_LIBRARY_AVAILABLE = Sender is not None


@dataclass(frozen=True)
class MetricRequest:
    """A single metric to send to a Zabbix trapper item."""

    server: str
    port: int
    host: str
    key: str
    value: str
    value_type: str = "numeric"
    timestamp: Optional[int] = None
    timeout: int = DEFAULT_TIMEOUT


@dataclass(frozen=True)
class SendResult:
    """Outcome returned by the integrated Sender library."""

    success: bool
    message: str
    output: str = ""
    returncode: int = 0
    duration_ms: int = 0


def app_data_dir() -> Path:
    """Return a per-user directory for settings and local history."""

    if os.name == "nt" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    elif os.name == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "zbx-sender"


def normalize_numeric(value: str) -> str:
    """Normalize Brazilian decimal commas to the format accepted by Zabbix."""

    candidate = value.strip().replace(",", ".")
    try:
        number = Decimal(candidate)
    except InvalidOperation as exc:
        raise ValueError("Informe um valor numérico válido.") from exc
    if not number.is_finite():
        raise ValueError("O valor numérico precisa ser finito.")

    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def parse_timestamp(value: str) -> Optional[int]:
    """Parse an optional epoch or local ISO-like timestamp."""

    candidate = value.strip()
    if not candidate:
        return None
    if candidate.isdigit():
        timestamp = int(candidate)
    else:
        parsed: Optional[datetime] = None
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(candidate, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    "Use timestamp em epoch ou no formato AAAA-MM-DD HH:MM:SS."
                ) from exc
        if parsed.tzinfo is None:
            timestamp = int(parsed.timestamp())
        else:
            timestamp = int(parsed.astimezone(timezone.utc).timestamp())

    if timestamp <= 0:
        raise ValueError("O timestamp precisa ser maior que zero.")
    return timestamp


def validate_request(request: MetricRequest) -> list[str]:
    """Return user-facing validation errors for a metric request."""

    errors: list[str] = []
    if not request.server.strip():
        errors.append("Informe o servidor Zabbix.")
    if not 1 <= request.port <= 65535:
        errors.append("A porta precisa estar entre 1 e 65535.")
    if not request.host.strip():
        errors.append("Informe o host monitorado.")
    if not request.key.strip():
        errors.append("Informe a chave do item trapper.")
    if any(char.isspace() for char in request.key):
        errors.append("A chave do item não pode conter espaços.")
    if not request.value.strip():
        errors.append("Informe o valor da métrica.")
    if request.value_type == "numeric" and request.value.strip():
        try:
            normalize_numeric(request.value)
        except ValueError as exc:
            errors.append(str(exc))
    if request.timestamp is not None and request.timestamp <= 0:
        errors.append("O timestamp precisa ser maior que zero.")
    if not 1 <= request.timeout <= 120:
        errors.append("O timeout precisa estar entre 1 e 120 segundos.")
    return errors


def sender_preview(request: MetricRequest) -> str:
    """Return a readable preview of the native zabbix_utils call."""

    if request.value_type == "numeric":
        try:
            value = normalize_numeric(request.value or "0")
        except ValueError:
            value = request.value or "<valor>"
    else:
        value = request.value
    value_literal = repr(value)
    timestamp = f", {request.timestamp}" if request.timestamp is not None else ""
    return (
        f"Sender(server={request.server or '<servidor>'!r}, port={request.port or DEFAULT_PORT})"
        f".send_value({request.host or '<host>'!r}, {request.key or '<chave>'!r}, "
        f"{value_literal}{timestamp})"
    )


def _response_summary(response: Any) -> str:
    """Format the official TrapperResponse for the history and UI."""

    return (
        f"processados: {response.processed}; "
        f"falhos: {response.failed}; "
        f"total: {response.total}; "
        f"tempo: {response.time}s"
    )


def send_metric(
    request: MetricRequest,
    sender_factory: Optional[Callable[..., Any]] = None,
) -> SendResult:
    """Send one metric directly through the official ``zabbix_utils`` Sender.

    ``sender_factory`` is intentionally optional and exists to make the
    transport easy to test without opening a network connection. Production
    callers use the official ``Sender`` class automatically.
    """

    errors = validate_request(request)
    if errors:
        return SendResult(False, errors[0], returncode=2)
    if Sender is None and sender_factory is None:
        return SendResult(
            False,
            "A biblioteca oficial zabbix_utils não está instalada.",
            returncode=127,
        )

    sender_class = sender_factory or Sender
    value = request.value if request.value_type != "numeric" else normalize_numeric(request.value)
    started = time.perf_counter()
    try:
        sender = sender_class(
            server=request.server,
            port=request.port,
            timeout=request.timeout,
        )
        response = sender.send_value(
            request.host,
            request.key,
            value,
            request.timestamp,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        output = _response_summary(response)
        if response.failed == 0 and response.processed >= 1:
            return SendResult(True, "Enviado com sucesso", output, 0, duration_ms)
        return SendResult(
            False,
            "O Zabbix recusou o envio. Verifique o host e a chave do item.",
            output,
            1,
            duration_ms,
        )
    except TimeoutError:
        return SendResult(
            False,
            f"Tempo limite excedido após {request.timeout} segundos.",
            returncode=124,
        )
    except Exception as exc:  # zabbix_utils maps socket/protocol errors to several types.
        return SendResult(
            False,
            "Não foi possível enviar a métrica ao Zabbix.",
            str(exc) or exc.__class__.__name__,
            1,
            int((time.perf_counter() - started) * 1000),
        )


class HistoryStore:
    """Small JSON-backed history store with safe recovery from malformed files."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or app_data_dir() / "history.json"

    def load(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def append(self, request: MetricRequest, result: SendResult) -> list[dict[str, Any]]:
        entries = self.load()
        entries.insert(0, history_record(request, result))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(entries[:MAX_HISTORY_ITEMS], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return entries[:MAX_HISTORY_ITEMS]

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def history_record(request: MetricRequest, result: SendResult) -> dict[str, Any]:
    """Create a serializable history record for tests and integrations."""

    return {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": request.host,
        "key": request.key,
        "value": request.value,
        "success": result.success,
        "message": result.message,
        "output": result.output,
        "duration_ms": result.duration_ms,
    }


def load_settings(path: Optional[Path] = None) -> dict[str, Any]:
    settings_path = path or app_data_dir() / "settings.json"
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict[str, Any], path: Optional[Path] = None) -> None:
    settings_path = path or app_data_dir() / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )


__all__ = [
    "APP_NAME",
    "DEFAULT_PORT",
    "DEFAULT_TIMEOUT",
    "HistoryStore",
    "MetricRequest",
    "SendResult",
    "app_data_dir",
    "history_record",
    "load_settings",
    "normalize_numeric",
    "parse_timestamp",
    "save_settings",
    "send_metric",
    "sender_preview",
    "validate_request",
]
