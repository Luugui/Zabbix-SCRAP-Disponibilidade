"""ZBX Sender - a compact CustomTkinter interface for zabbix_sender."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

from zbx_sender_service import (
    APP_NAME,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    HistoryStore,
    MetricRequest,
    SendResult,
    command_preview,
    find_sender_executable,
    load_settings,
    parse_timestamp,
    save_settings,
    send_metric,
    validate_request,
)


# Palette mirrors the approved mockup: graphite surfaces, teal action color,
# green success states and restrained borders.
BG = "#0d1117"
SIDEBAR = "#101820"
PANEL = "#141d27"
PANEL_DARK = "#111923"
INPUT = "#101821"
BORDER = "#273544"
ACCENT = "#27c8bb"
ACCENT_HOVER = "#1fa99e"
ACCENT_SOFT = "#123238"
TEXT = "#f4f7fb"
MUTED = "#91a0b3"
SUCCESS = "#35d58a"
SUCCESS_SOFT = "#102f2a"
DANGER = "#ff7d86"
DANGER_SOFT = "#351c23"
WARNING = "#ffbf69"

VALUE_TYPE_LABELS = {"Numérico": "numeric", "Texto": "text"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "server": "zabbix.interno.local",
    "port": str(DEFAULT_PORT),
    "host": "api-prod-01",
    "key": "api.health",
    "value": "1",
    "value_type": "Numérico",
    "timestamp": "",
    "timeout": str(DEFAULT_TIMEOUT),
    "sender_path": "",
}


class ZbxSenderApp(ctk.CTk):
    """Main window for sending one trapper value at a time."""

    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title(APP_NAME)
        self.geometry("1280x800")
        self.minsize(1040, 680)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-Return>", lambda _event: self._on_send())
        self.bind("<Command-Return>", lambda _event: self._on_send())

        stored = load_settings()
        self.settings: dict[str, Any] = {**DEFAULT_SETTINGS, **stored}
        self.history_store = HistoryStore()
        self.sender_path: Optional[str] = find_sender_executable(
            self.settings.get("sender_path") or None
        )
        self.current_view = "send"
        self.view_frame: Optional[ctk.CTkFrame] = None
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self.recent_history_frame: Optional[ctk.CTkFrame] = None
        self.history_list_frame: Optional[ctk.CTkFrame] = None
        self.feedback_label: Optional[ctk.CTkLabel] = None
        self.send_button: Optional[ctk.CTkButton] = None
        self.status_dot: Optional[ctk.CTkLabel] = None
        self.status_text: Optional[ctk.CTkLabel] = None
        self.command_label: Optional[ctk.CTkLabel] = None
        self.form_vars: dict[str, tk.StringVar] = {}
        self.value_textbox: Optional[ctk.CTkTextbox] = None
        self.form_trace_ids: list[tuple[tk.StringVar, str]] = []

        self._build_shell()
        self.show_send_view()

    # ------------------------------------------------------------------
    # Shell and navigation
    # ------------------------------------------------------------------
    def _build_shell(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=236)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        sidebar = ctk.CTkFrame(self, width=236, corner_radius=0, fg_color=SIDEBAR)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(4, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, padx=22, pady=(28, 36), sticky="ew")
        brand.grid_columnconfigure(1, weight=1)
        mark = ctk.CTkLabel(
            brand,
            text="Z",
            width=42,
            height=42,
            corner_radius=10,
            fg_color=ACCENT,
            text_color=BG,
            font=ctk.CTkFont(size=26, weight="bold"),
        )
        mark.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(
            brand,
            text="ZBX Sender",
            text_color=TEXT,
            font=ctk.CTkFont(size=17, weight="bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            brand,
            text="Envio rápido para itens trapper",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
            anchor="w",
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))

        ctk.CTkLabel(
            sidebar,
            text="WORKSPACE",
            text_color="#5e6d80",
            font=ctk.CTkFont(size=10, weight="bold"),
            anchor="w",
        ).grid(row=1, column=0, padx=22, pady=(0, 10), sticky="ew")

        nav_items = [
            ("send", "↗", "Enviar métrica"),
            ("history", "◷", "Histórico"),
            ("settings", "⚙", "Configurações"),
        ]
        for row, (key, icon, label) in enumerate(nav_items, start=2):
            button = ctk.CTkButton(
                sidebar,
                text=f"  {icon}    {label}",
                height=44,
                corner_radius=8,
                border_width=0,
                fg_color="transparent",
                hover_color="#1a2935",
                text_color=MUTED,
                font=ctk.CTkFont(size=13),
                anchor="w",
                command=lambda view=key: self._navigate(view),
            )
            button.grid(row=row, column=0, padx=10, pady=3, sticky="ew")
            self.nav_buttons[key] = button

        sender_hint = ctk.CTkFrame(sidebar, fg_color=PANEL_DARK, corner_radius=10)
        sender_hint.grid(row=5, column=0, padx=18, pady=(0, 22), sticky="ew")
        sender_hint.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            sender_hint,
            text="EXECUTOR",
            text_color="#5e6d80",
            font=ctk.CTkFont(size=9, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=13, pady=(12, 2), sticky="w")
        self.sidebar_sender_label = ctk.CTkLabel(
            sender_hint,
            text="Detectando…",
            text_color=MUTED,
            font=ctk.CTkFont(size=10),
            anchor="w",
            wraplength=180,
        )
        self.sidebar_sender_label.grid(row=1, column=0, padx=13, pady=(0, 12), sticky="w")
        self._refresh_sender_labels()

        self.content_container = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content_container.grid(row=0, column=1, padx=(0, 18), pady=(18, 0), sticky="nsew")
        self.content_container.grid_rowconfigure(0, weight=1)
        self.content_container.grid_columnconfigure(0, weight=1)

        status_bar = ctk.CTkFrame(self, height=38, corner_radius=0, fg_color="#101821")
        status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        status_bar.grid_columnconfigure(1, weight=1)
        self.status_dot = ctk.CTkLabel(
            status_bar, text="●", text_color=SUCCESS, font=ctk.CTkFont(size=14)
        )
        self.status_dot.grid(row=0, column=0, padx=(20, 5), pady=8)
        self.status_text = ctk.CTkLabel(
            status_bar,
            text="Pronto para enviar",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self.status_text.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(
            status_bar,
            text="ZBX Sender · 1.0",
            text_color="#5e6d80",
            font=ctk.CTkFont(size=10),
        ).grid(row=0, column=2, padx=20)

    def _navigate(self, view: str) -> None:
        if view == self.current_view and self.view_frame is not None:
            return
        self.current_view = view
        if view == "send":
            self.show_send_view()
        elif view == "history":
            self.show_history_view()
        else:
            self.show_settings_view()

    def _set_active_nav(self, active: str) -> None:
        for key, button in self.nav_buttons.items():
            is_active = key == active
            button.configure(
                fg_color=ACCENT_SOFT if is_active else "transparent",
                text_color=ACCENT if is_active else MUTED,
            )

    def _clear_view(self) -> ctk.CTkFrame:
        if self.view_frame is not None:
            self.view_frame.destroy()
        self.connection_dot = None
        self.connection_label = None
        self.form_trace_ids.clear()
        self.view_frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.view_frame.grid(row=0, column=0, sticky="nsew")
        self.view_frame.grid_rowconfigure(1, weight=1)
        self.view_frame.grid_columnconfigure(0, weight=1)
        return self.view_frame

    # ------------------------------------------------------------------
    # Reusable widgets
    # ------------------------------------------------------------------
    def _header(
        self, parent: ctk.CTkFrame, icon: str, title: str, subtitle: str = ""
    ) -> ctk.CTkFrame:
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, padx=20, pady=(4, 18), sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text=icon,
            text_color=ACCENT,
            font=ctk.CTkFont(size=31),
        ).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(
            header,
            text=title,
            text_color=TEXT,
            font=ctk.CTkFont(size=26, weight="bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w")
        if subtitle:
            ctk.CTkLabel(
                header,
                text=subtitle,
                text_color=MUTED,
                font=ctk.CTkFont(size=11),
                anchor="w",
            ).grid(row=1, column=1, sticky="w", pady=(3, 0))
        return header

    def _card(self, parent: ctk.CTkFrame, **grid_kwargs: Any) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=PANEL,
            border_color=BORDER,
            border_width=1,
            corner_radius=12,
        )
        card.grid(**grid_kwargs)
        return card

    def _section_title(self, parent: ctk.CTkFrame, icon: str, title: str) -> None:
        ctk.CTkLabel(
            parent,
            text=f"{icon}   {title}",
            text_color=TEXT,
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(18, 14), sticky="w")

    def _entry_field(
        self,
        parent: ctk.CTkFrame,
        row: int,
        column: int,
        label: str,
        key: str,
        placeholder: str = "",
        columnspan: int = 1,
    ) -> ctk.CTkEntry:
        parent.grid_columnconfigure(column, weight=1)
        ctk.CTkLabel(
            parent,
            text=label,
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).grid(row=row, column=column, columnspan=columnspan, padx=20, pady=(0, 6), sticky="w")
        variable = self.form_vars.setdefault(
            key, tk.StringVar(self, value=str(self.settings.get(key, "")))
        )
        entry = ctk.CTkEntry(
            parent,
            textvariable=variable,
            placeholder_text=placeholder,
            height=38,
            fg_color=INPUT,
            border_color=BORDER,
            text_color=TEXT,
            placeholder_text_color="#5e6d80",
            corner_radius=7,
            font=ctk.CTkFont(size=12),
        )
        entry.grid(
            row=row + 1,
            column=column,
            columnspan=columnspan,
            padx=20,
            pady=(0, 16),
            sticky="ew",
        )
        trace_id = variable.trace_add("write", lambda *_args: self._update_command_preview())
        self.form_trace_ids.append((variable, trace_id))
        return entry

    def _make_status_badge(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        badge = ctk.CTkFrame(parent, fg_color=SUCCESS_SOFT, corner_radius=18)
        badge.grid(row=0, column=2, padx=(12, 0), sticky="e")
        self.connection_dot = ctk.CTkLabel(
            badge, text="●", text_color=SUCCESS, font=ctk.CTkFont(size=13)
        )
        self.connection_dot.grid(row=0, column=0, padx=(12, 5), pady=7)
        self.connection_label = ctk.CTkLabel(
            badge,
            text="Pronto",
            text_color=SUCCESS,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.connection_label.grid(row=0, column=1, padx=(0, 12), pady=7)
        self._refresh_sender_labels()
        return badge

    # ------------------------------------------------------------------
    # Send view
    # ------------------------------------------------------------------
    def show_send_view(self) -> None:
        self.current_view = "send"
        self._set_active_nav("send")
        view = self._clear_view()
        view.grid_columnconfigure(0, weight=1)
        self.form_vars = {}
        self.value_textbox = None

        header = self._header(view, "➤", "Enviar métrica", "Envie um valor para um item trapper do Zabbix")
        header.grid_columnconfigure(2, weight=0)
        self._make_status_badge(header)

        body = ctk.CTkFrame(view, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0, minsize=330)

        form = ctk.CTkScrollableFrame(body, fg_color="transparent", corner_radius=0)
        form.grid(row=0, column=0, padx=(20, 12), sticky="nsew")
        form.grid_columnconfigure(0, weight=1)

        destination = self._card(form, row=0, column=0, padx=0, pady=(0, 14), sticky="ew")
        destination.grid_columnconfigure(0, weight=3)
        destination.grid_columnconfigure(1, weight=2)
        self._section_title(destination, "▤", "Destino Zabbix")
        self._entry_field(destination, 1, 0, "Servidor Zabbix", "server", "zabbix.interno.local")
        self._entry_field(destination, 1, 1, "Porta", "port", "10051")
        self._entry_field(destination, 3, 0, "Host monitorado", "host", "api-prod-01")
        self._entry_field(destination, 3, 1, "Chave do item", "key", "api.health")

        metric = self._card(form, row=1, column=0, padx=0, pady=(0, 14), sticky="ew")
        metric.grid_columnconfigure(0, weight=1)
        metric.grid_columnconfigure(1, weight=0, minsize=150)
        self._section_title(metric, "▥", "Valor da métrica")
        ctk.CTkLabel(
            metric,
            text="Valor",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).grid(row=1, column=0, padx=20, pady=(0, 6), sticky="w")
        self.value_textbox = ctk.CTkTextbox(
            metric,
            height=78,
            fg_color=INPUT,
            border_color=BORDER,
            border_width=1,
            text_color=TEXT,
            corner_radius=7,
            wrap="word",
            font=ctk.CTkFont(size=13),
        )
        self.value_textbox.grid(row=2, column=0, padx=(20, 10), pady=(0, 14), sticky="ew")
        self.value_textbox.insert("1.0", str(self.settings.get("value", "1")))
        self.value_textbox.bind("<KeyRelease>", lambda _event: self._update_command_preview())

        ctk.CTkLabel(
            metric,
            text="Tipo",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).grid(row=1, column=1, padx=(0, 20), pady=(0, 6), sticky="w")
        self.form_vars["value_type"] = tk.StringVar(
            self, value=str(self.settings.get("value_type", "Numérico"))
        )
        type_selector = ctk.CTkComboBox(
            metric,
            values=list(VALUE_TYPE_LABELS),
            variable=self.form_vars["value_type"],
            height=38,
            fg_color=INPUT,
            border_color=BORDER,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=PANEL,
            dropdown_hover_color=ACCENT_SOFT,
            text_color=TEXT,
            corner_radius=7,
            font=ctk.CTkFont(size=12),
            command=lambda _value: self._update_command_preview(),
        )
        type_selector.grid(row=2, column=1, padx=(0, 20), pady=(0, 14), sticky="ew")

        self._entry_field(metric, 3, 0, "Timestamp (opcional)", "timestamp", "AAAA-MM-DD HH:MM:SS", 2)

        action_row = ctk.CTkFrame(metric, fg_color="transparent")
        action_row.grid(row=5, column=0, columnspan=2, padx=20, pady=(0, 18), sticky="ew")
        action_row.grid_columnconfigure(1, weight=1)
        self.send_button = ctk.CTkButton(
            action_row,
            text="➤   Enviar agora",
            width=190,
            height=42,
            corner_radius=8,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=BG,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_send,
        )
        self.send_button.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            action_row,
            text="Ctrl + Enter para enviar",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
        ).grid(row=0, column=1, padx=14, sticky="w")
        self.feedback_label = ctk.CTkLabel(
            action_row,
            text="",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="e",
        )
        self.feedback_label.grid(row=0, column=2, sticky="e")

        command_card = self._card(form, row=2, column=0, padx=0, pady=(0, 14), sticky="ew")
        command_card.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(command_card, fg_color="transparent")
        top.grid(row=0, column=0, padx=14, pady=(10, 4), sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            top,
            text="›  Comando equivalente",
            text_color=MUTED,
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            top,
            text="somente visualização",
            text_color="#5e6d80",
            font=ctk.CTkFont(size=10),
            anchor="e",
        ).grid(row=0, column=1, sticky="e")
        self.command_label = ctk.CTkLabel(
            command_card,
            text="",
            height=38,
            fg_color=INPUT,
            corner_radius=7,
            text_color="#b7c5d7",
            font=ctk.CTkFont(family="DejaVu Sans Mono", size=10),
            anchor="w",
        )
        self.command_label.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="ew")
        self._update_command_preview()

        history_panel = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
        history_panel.grid(row=0, column=1, padx=(0, 0), sticky="nsew")
        history_panel.grid_rowconfigure(1, weight=1)
        history_panel.grid_columnconfigure(0, weight=1)
        title_row = ctk.CTkFrame(history_panel, fg_color="transparent")
        title_row.grid(row=0, column=0, padx=18, pady=(18, 14), sticky="ew")
        title_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            title_row,
            text="◷",
            text_color="#b7c5d7",
            font=ctk.CTkFont(size=25),
        ).grid(row=0, column=0, padx=(0, 10))
        ctk.CTkLabel(
            title_row,
            text="Últimos envios",
            text_color=TEXT,
            font=ctk.CTkFont(size=17, weight="bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w")
        self.recent_history_frame = ctk.CTkScrollableFrame(
            history_panel, fg_color="transparent", corner_radius=0
        )
        self.recent_history_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.recent_history_frame.grid_columnconfigure(0, weight=1)
        self._render_history_rows(self.recent_history_frame, limit=8, compact=True)

    def _update_command_preview(self) -> None:
        if self.command_label is None:
            return
        def get_var(key: str, fallback: str = "") -> str:
            variable = self.form_vars.get(key)
            return variable.get() if variable is not None else fallback

        try:
            port = int(get_var("port", str(DEFAULT_PORT)) or DEFAULT_PORT)
        except ValueError:
            port = DEFAULT_PORT
        value = self.value_textbox.get("1.0", "end-1c") if self.value_textbox else ""
        timestamp_text = get_var("timestamp")
        timestamp = None
        try:
            timestamp = parse_timestamp(timestamp_text)
        except ValueError:
            timestamp = 1
        request = MetricRequest(
            server=get_var("server"),
            port=port,
            host=get_var("host"),
            key=get_var("key"),
            value=value,
            value_type=VALUE_TYPE_LABELS.get(get_var("value_type", "Numérico"), "numeric"),
            timestamp=timestamp,
            timeout=DEFAULT_TIMEOUT,
        )
        self.command_label.configure(text=command_preview(request, self._display_sender_name()))

    def _display_sender_name(self) -> str:
        return Path(self.sender_path).name if self.sender_path else "zabbix_sender"

    def _on_send(self) -> None:
        if self.send_button is not None and str(self.send_button.cget("state")) == "disabled":
            return
        try:
            request = self._request_from_form()
        except ValueError as exc:
            self._show_feedback(str(exc), success=False)
            self._set_status(str(exc), success=False)
            return

        self._set_busy(True)
        self._set_status("Enviando métrica…", success=None)
        configured_sender = str(self.settings.get("sender_path") or "").strip() or None

        def worker() -> None:
            result = send_metric(request, configured_sender)
            self.after(0, lambda: self._finish_send(request, result))

        threading.Thread(target=worker, daemon=True, name="zbx-sender-worker").start()

    def _request_from_form(self) -> MetricRequest:
        def get_var(key: str) -> str:
            return self.form_vars[key].get().strip()

        try:
            port = int(get_var("port"))
        except (KeyError, ValueError) as exc:
            raise ValueError("A porta precisa ser um número entre 1 e 65535.") from exc
        value = self.value_textbox.get("1.0", "end-1c").strip() if self.value_textbox else ""
        try:
            timestamp = parse_timestamp(get_var("timestamp"))
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        request = MetricRequest(
            server=get_var("server"),
            port=port,
            host=get_var("host"),
            key=get_var("key"),
            value=value,
            value_type=VALUE_TYPE_LABELS.get(get_var("value_type"), "numeric"),
            timestamp=timestamp,
            timeout=self._timeout_value(),
        )
        errors = validate_request(request)
        if errors:
            raise ValueError(errors[0])
        return request

    def _timeout_value(self) -> int:
        try:
            return int(str(self.settings.get("timeout", DEFAULT_TIMEOUT)))
        except (ValueError, TypeError):
            return DEFAULT_TIMEOUT

    def _finish_send(self, request: MetricRequest, result: SendResult) -> None:
        self._set_busy(False)
        self.history_store.append(request, result)
        self._show_feedback(result.message, result.success)
        self._set_status(result.message, result.success)
        if self.recent_history_frame is not None:
            self._render_history_rows(self.recent_history_frame, limit=8, compact=True)
        if not result.success and result.output:
            self._show_result_details(result)

    def _show_result_details(self, result: SendResult) -> None:
        details = result.output.strip()
        if not details:
            return
        self.after(80, lambda: messagebox.showerror("Falha no envio", f"{result.message}\n\n{details}", parent=self))

    def _set_busy(self, busy: bool) -> None:
        if self.send_button is None:
            return
        if busy:
            self.send_button.configure(state="disabled", text="Enviando…")
        else:
            self.send_button.configure(state="normal", text="➤   Enviar agora")

    def _show_feedback(self, message: str, success: bool) -> None:
        if self.feedback_label is None:
            return
        self.feedback_label.configure(
            text=message,
            text_color=SUCCESS if success else DANGER,
        )

    # ------------------------------------------------------------------
    # History view
    # ------------------------------------------------------------------
    def show_history_view(self) -> None:
        self.current_view = "history"
        self._set_active_nav("history")
        view = self._clear_view()
        self._header(view, "◷", "Histórico", "Envios recentes realizados por este computador")
        card = self._card(view, row=1, column=0, padx=20, pady=(0, 20), sticky="nsew")
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)
        toolbar = ctk.CTkFrame(card, fg_color="transparent")
        toolbar.grid(row=0, column=0, padx=18, pady=(14, 8), sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            toolbar,
            text="Os registros ficam armazenados localmente em JSON.",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            toolbar,
            text="Limpar histórico",
            width=132,
            height=32,
            corner_radius=7,
            fg_color=DANGER_SOFT,
            hover_color="#4a252c",
            text_color=DANGER,
            font=ctk.CTkFont(size=11),
            command=self._clear_history,
        ).grid(row=0, column=1, sticky="e")
        self.history_list_frame = ctk.CTkScrollableFrame(card, fg_color="transparent")
        self.history_list_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.history_list_frame.grid_columnconfigure(0, weight=1)
        self._render_history_rows(self.history_list_frame, limit=None, compact=False)

    def _render_history_rows(
        self, parent: ctk.CTkFrame, limit: Optional[int], compact: bool
    ) -> None:
        for child in parent.winfo_children():
            child.destroy()
        entries = self.history_store.load()
        if limit is not None:
            entries = entries[:limit]
        if not entries:
            empty = ctk.CTkFrame(parent, fg_color=PANEL_DARK, corner_radius=9)
            empty.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
            ctk.CTkLabel(
                empty,
                text="Nenhum envio registrado ainda.",
                text_color=MUTED,
                font=ctk.CTkFont(size=11),
            ).pack(padx=16, pady=22)
            return

        for row, entry in enumerate(entries):
            success = bool(entry.get("success"))
            item = ctk.CTkFrame(
                parent,
                fg_color=SUCCESS_SOFT if success else PANEL_DARK,
                border_color="#1d5147" if success else BORDER,
                border_width=1,
                corner_radius=8,
            )
            item.grid(row=row, column=0, padx=4, pady=(0, 8), sticky="ew")
            item.grid_columnconfigure(1, weight=1)
            icon = "✓" if success else "!"
            ctk.CTkLabel(
                item,
                text=icon,
                width=26,
                height=26,
                corner_radius=13,
                fg_color=SUCCESS if success else DANGER,
                text_color=BG,
                font=ctk.CTkFont(size=12, weight="bold"),
            ).grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=10)
            key_text = f"{entry.get('key', '—')}  ·  {entry.get('value', '—')}"
            if compact:
                key_text += f"  ·  {self._relative_time(entry.get('created_at', ''))}"
            else:
                key_text += f"  ·  {entry.get('host', '—')}"
            button = ctk.CTkButton(
                item,
                text=key_text,
                anchor="w",
                fg_color="transparent",
                hover_color="#1a2935",
                text_color=TEXT,
                height=24,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda record=entry: self._show_history_entry(record),
            )
            button.grid(row=0, column=1, padx=(0, 8), pady=(8, 0), sticky="ew")
            detail = entry.get("message", "")
            if not compact:
                detail = f"{detail}  ·  {self._relative_time(entry.get('created_at', ''))}"
            ctk.CTkLabel(
                item,
                text=detail,
                text_color=SUCCESS if success else DANGER,
                font=ctk.CTkFont(size=10),
                anchor="w",
            ).grid(row=1, column=1, padx=(0, 8), pady=(0, 9), sticky="w")

    def _relative_time(self, value: str) -> str:
        if not value:
            return "agora"
        try:
            then = datetime.fromisoformat(value)
            seconds = max(0, int((datetime.now().astimezone() - then).total_seconds()))
        except ValueError:
            return "agora"
        if seconds < 60:
            return "agora"
        if seconds < 3600:
            return f"há {seconds // 60} min"
        if seconds < 86400:
            return f"há {seconds // 3600} h"
        return f"há {seconds // 86400} d"

    def _show_history_entry(self, entry: dict[str, Any]) -> None:
        output = str(entry.get("output") or "Sem saída retornada pelo processo.")
        details = (
            f"Host: {entry.get('host', '—')}\n"
            f"Chave: {entry.get('key', '—')}\n"
            f"Valor: {entry.get('value', '—')}\n\n"
            f"{output}"
        )
        messagebox.showinfo("Detalhes do envio", details, parent=self)

    def _clear_history(self) -> None:
        if not self.history_store.load():
            return
        if not messagebox.askyesno("Limpar histórico", "Excluir todos os registros locais?", parent=self):
            return
        self.history_store.clear()
        if self.history_list_frame is not None:
            self._render_history_rows(self.history_list_frame, limit=None, compact=False)
        self._set_status("Histórico limpo", success=True)

    # ------------------------------------------------------------------
    # Settings view
    # ------------------------------------------------------------------
    def show_settings_view(self) -> None:
        self.current_view = "settings"
        self._set_active_nav("settings")
        view = self._clear_view()
        self._header(view, "⚙", "Configurações", "Ajuste o executor e o comportamento do envio")
        content = ctk.CTkFrame(view, fg_color="transparent")
        content.grid(row=1, column=0, padx=20, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(2, weight=1)

        executable_card = self._card(content, row=0, column=0, padx=0, pady=(0, 14), sticky="ew")
        executable_card.grid_columnconfigure(0, weight=1)
        self._section_title(executable_card, "▣", "Executor zabbix_sender")
        ctk.CTkLabel(
            executable_card,
            text="Use o executável instalado no PATH ou indique um arquivo local.",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).grid(row=1, column=0, padx=20, pady=(0, 6), sticky="w")
        self.settings_sender_var = tk.StringVar(self, value=str(self.settings.get("sender_path", "")))
        sender_entry = ctk.CTkEntry(
            executable_card,
            textvariable=self.settings_sender_var,
            height=38,
            fg_color=INPUT,
            border_color=BORDER,
            text_color=TEXT,
            corner_radius=7,
            font=ctk.CTkFont(size=12),
        )
        sender_entry.grid(row=2, column=0, padx=(20, 10), pady=(0, 18), sticky="ew")
        ctk.CTkButton(
            executable_card,
            text="Procurar…",
            width=105,
            height=38,
            corner_radius=7,
            fg_color="#1b2a38",
            hover_color="#25394b",
            text_color=TEXT,
            font=ctk.CTkFont(size=11),
            command=self._browse_sender,
        ).grid(row=2, column=1, padx=(0, 20), pady=(0, 18), sticky="e")
        executable_card.grid_columnconfigure(1, weight=0)

        behavior_card = self._card(content, row=1, column=0, padx=0, pady=(0, 14), sticky="ew")
        behavior_card.grid_columnconfigure(0, weight=1)
        self._section_title(behavior_card, "◷", "Comportamento")
        ctk.CTkLabel(
            behavior_card,
            text="Timeout do envio (segundos)",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).grid(row=1, column=0, padx=20, pady=(0, 6), sticky="w")
        self.settings_timeout_var = tk.StringVar(self, value=str(self.settings.get("timeout", DEFAULT_TIMEOUT)))
        ctk.CTkEntry(
            behavior_card,
            textvariable=self.settings_timeout_var,
            width=160,
            height=38,
            fg_color=INPUT,
            border_color=BORDER,
            text_color=TEXT,
            corner_radius=7,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, padx=20, pady=(0, 18), sticky="w")

        info_card = self._card(content, row=2, column=0, padx=0, pady=(0, 14), sticky="nsew")
        info_card.grid_columnconfigure(0, weight=1)
        self._section_title(info_card, "i", "Sobre o aplicativo")
        info = (
            "O ZBX Sender é uma interface gráfica para o comando oficial zabbix_sender.\n\n"
            "Cada envio abre uma conexão com o Zabbix Server, envia um único valor para o item trapper "
            "e encerra o processo. O histórico fica salvo somente neste computador."
        )
        ctk.CTkLabel(
            info_card,
            text=info,
            text_color=MUTED,
            justify="left",
            anchor="nw",
            wraplength=720,
            font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, padx=20, pady=(0, 18), sticky="nw")

        ctk.CTkButton(
            content,
            text="Salvar configurações",
            width=190,
            height=42,
            corner_radius=8,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=BG,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._save_settings_from_view,
        ).grid(row=3, column=0, padx=0, pady=(0, 20), sticky="w")

    def _browse_sender(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione o executável zabbix_sender",
            filetypes=[("Executável", "*.exe"), ("Todos os arquivos", "*.*")],
        )
        if selected:
            self.settings_sender_var.set(selected)

    def _save_settings_from_view(self) -> None:
        raw_timeout = self.settings_timeout_var.get().strip()
        try:
            timeout = int(raw_timeout)
        except ValueError:
            self._set_status("O timeout precisa ser um número inteiro.", success=False)
            return
        if not 1 <= timeout <= 120:
            self._set_status("O timeout precisa estar entre 1 e 120 segundos.", success=False)
            return
        self.settings["sender_path"] = self.settings_sender_var.get().strip()
        self.settings["timeout"] = str(timeout)
        save_settings(self.settings)
        self.sender_path = find_sender_executable(self.settings.get("sender_path") or None)
        self._refresh_sender_labels()
        self._set_status("Configurações salvas", success=True)

    # ------------------------------------------------------------------
    # Persistence and status
    # ------------------------------------------------------------------
    def _refresh_sender_labels(self) -> None:
        self.sender_path = find_sender_executable(self.settings.get("sender_path") or None)
        if hasattr(self, "sidebar_sender_label"):
            if self.sender_path:
                self.sidebar_sender_label.configure(
                    text=Path(self.sender_path).name, text_color=SUCCESS
                )
            else:
                self.sidebar_sender_label.configure(
                    text="Não encontrado no PATH", text_color=WARNING
                )
        if (
            getattr(self, "connection_label", None) is not None
            and self.connection_label.winfo_exists()
        ):
            if self.sender_path:
                self.connection_label.configure(text="Pronto", text_color=SUCCESS)
                self.connection_dot.configure(text_color=SUCCESS)
            else:
                self.connection_label.configure(text="Atenção", text_color=WARNING)
                self.connection_dot.configure(text_color=WARNING)

    def _set_status(self, message: str, success: Optional[bool]) -> None:
        if self.status_text is not None:
            self.status_text.configure(text=message, text_color=SUCCESS if success is True else DANGER if success is False else MUTED)
        if self.status_dot is not None:
            self.status_dot.configure(text_color=SUCCESS if success is not False else DANGER)

    def _save_current_form(self) -> None:
        if not self.form_vars:
            return
        for key in ("server", "port", "host", "key", "timestamp", "value_type"):
            if key in self.form_vars:
                self.settings[key] = self.form_vars[key].get()
        if self.value_textbox is not None:
            self.settings["value"] = self.value_textbox.get("1.0", "end-1c").strip()

    def _on_close(self) -> None:
        self._save_current_form()
        save_settings(self.settings)
        self.destroy()


def main() -> None:
    app = ZbxSenderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
