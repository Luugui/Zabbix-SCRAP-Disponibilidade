"""Core services for the ZBX Sender desktop application.

The GUI deliberately delegates transport to the official ``zabbix_sender``
command. This keeps the application small, compatible with existing Zabbix
installations, and faithful to the sender's command-line behavior.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional, Sequence


APP_NAME = "ZBX Sender"
DEFAULT_PORT = 10051
DEFAULT_TIMEOUT = 10
MAX_HISTORY_ITEMS = 30


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
    """Outcome returned by the sender process."""

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


def find_sender_executable(configured_path: Optional[str] = None) -> Optional[str]:
    """Find an existing zabbix_sender executable.

    The lookup order is: explicit configured path, a bundled ``bin`` folder
    next to the application, then the operating system PATH.
    """

    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())

    application_dir = Path(__file__).resolve().parent
    names = ("zabbix_sender.exe", "zabbix_sender") if os.name == "nt" else ("zabbix_sender",)
    for name in names:
        candidates.append(application_dir / "bin" / name)

    path_candidate = shutil.which("zabbix_sender")
    if path_candidate:
        candidates.append(Path(path_candidate))

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None


def normalize_numeric(value: str) -> str:
    """Normalize Brazilian decimal commas to the dot format accepted by Zabbix."""

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


def _quote_payload_field(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def build_timestamp_payload(request: MetricRequest) -> str:
    """Build the input-file line consumed by zabbix_sender ``-T -i``."""

    if request.timestamp is None:
        raise ValueError("Timestamp obrigatório para payload com timestamp.")
    value = request.value if request.value_type != "numeric" else normalize_numeric(request.value)
    return (
        f"{_quote_payload_field(request.host)} {request.key} "
        f"{request.timestamp} {_quote_payload_field(value)}\n"
    )


def build_command(
    request: MetricRequest,
    executable: str = "zabbix_sender",
    input_file: Optional[str] = None,
) -> list[str]:
    """Build a shell-free argv list for the official sender."""

    if request.timestamp is not None:
        if not input_file:
            raise ValueError("É necessário um arquivo de entrada para timestamp.")
        return [
            executable,
            "-z",
            request.server,
            "-p",
            str(request.port),
            "-T",
            "-i",
            input_file,
        ]

    value = request.value if request.value_type != "numeric" else normalize_numeric(request.value)
    return [
        executable,
        "-z",
        request.server,
        "-p",
        str(request.port),
        "-s",
        request.host,
        "-k",
        request.key,
        "-o",
        value,
    ]


def command_preview(request: MetricRequest, executable: str = "zabbix_sender") -> str:
    """Return a compact human-readable equivalent command for the UI."""

    try:
        if request.timestamp is not None:
            args = build_command(request, executable, "<payload temporário>")
        else:
            args = build_command(request, executable)
    except (ValueError, TypeError):
        args = [
            executable,
            "-z",
            request.server or "<servidor>",
            "-p",
            str(request.port or DEFAULT_PORT),
            "-s",
            request.host or "<host>",
            "-k",
            request.key or "<chave>",
            "-o",
            request.value or "<valor>",
        ]

    rendered: list[str] = []
    for arg in args:
        if " " in arg or "<" in arg or ">" in arg:
            rendered.append(f'"{arg}"')
        else:
            rendered.append(arg)
    return " ".join(rendered)


def _combine_process_output(stdout: str, stderr: str) -> str:
    parts = [part.strip() for part in (stdout, stderr) if part and part.strip()]
    return "\n".join(parts)


def send_metric(
    request: MetricRequest,
    executable: Optional[str] = None,
) -> SendResult:
    """Send one metric through zabbix_sender without invoking a shell."""

    errors = validate_request(request)
    if errors:
        return SendResult(False, errors[0], returncode=2)

    sender = find_sender_executable(executable)
    if not sender:
        return SendResult(
            False,
            "zabbix_sender não encontrado. Instale-o ou indique o caminho em Configurações.",
            returncode=127,
        )

    temporary_path: Optional[str] = None
    try:
        if request.timestamp is not None:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".txt", delete=False
            ) as payload_file:
                payload_file.write(build_timestamp_payload(request))
                temporary_path = payload_file.name
            command = build_command(request, sender, temporary_path)
        else:
            command = build_command(request, sender)

        started = time.perf_counter()
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=request.timeout,
            check=False,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        output = _combine_process_output(completed.stdout, completed.stderr)
        if completed.returncode == 0:
            return SendResult(True, "Enviado com sucesso", output, 0, duration_ms)
        return SendResult(
            False,
            "O Zabbix recusou o envio. Verifique o servidor, host e chave do item.",
            output,
            completed.returncode,
            duration_ms,
        )
    except subprocess.TimeoutExpired:
        return SendResult(
            False,
            f"Tempo limite excedido após {request.timeout} segundos.",
            returncode=124,
        )
    except OSError as exc:
        return SendResult(False, f"Não foi possível executar o zabbix_sender: {exc}", returncode=126)
    finally:
        if temporary_path:
            try:
                Path(temporary_path).unlink(missing_ok=True)
            except OSError:
                pass


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
        entries.insert(
            0,
            {
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "host": request.host,
                "key": request.key,
                "value": request.value,
                "success": result.success,
                "message": result.message,
                "output": result.output,
                "duration_ms": result.duration_ms,
            },
        )
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
    "build_command",
    "build_timestamp_payload",
    "command_preview",
    "find_sender_executable",
    "history_record",
    "load_settings",
    "normalize_numeric",
    "parse_timestamp",
    "save_settings",
    "send_metric",
    "validate_request",
]
