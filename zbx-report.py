import argparse
import asyncio
import configparser
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlencode

import pandas as pd
from playwright.async_api import async_playwright


LOGGER_NAME = "zabbix_report"


@dataclass(frozen=True)
class Settings:
    zabbix_url: str
    username: str
    password: str
    from_time: str
    to_time: str
    filters: dict[str, list[dict[str, str]]]
    output_dir: Path
    log_dir: Path
    max_attempts: int
    retry_delay_seconds: int
    retry_backoff: float
    log_level: str


def _resolve_value(value: str, env_name: Optional[str] = None) -> str:
    """Resolve ${VAR}, env:VAR and an optional explicit environment override."""
    value = (value or "").strip()

    if env_name and os.getenv(env_name) is not None:
        return os.environ[env_name].strip()

    if value.startswith("env:"):
        return os.getenv(value[4:].strip(), "").strip()

    if value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1].strip(), "").strip()

    return os.path.expandvars(value)


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def _period_from_config(general: configparser.SectionProxy) -> tuple[str, str]:
    """Return the configured interval or the previous complete calendar day."""
    mode = general.get("PERIOD_MODE", "configured").strip().lower()
    if mode in {"previous_day", "previous-day", "ontem"}:
        day = datetime.now().date() - timedelta(days=1)
        return (
            f"{day:%Y-%m-%d} 00:00:00",
            f"{day:%Y-%m-%d} 23:59:59",
        )

    from_time = _resolve_value(general.get("FROM", ""))
    to_time = _resolve_value(general.get("TO", ""))
    if not from_time or not to_time:
        raise ValueError(
            "FROM e TO são obrigatórios quando PERIOD_MODE=configured."
        )
    return from_time, to_time


def load_settings(config_path: Path, cli_max_attempts: Optional[int] = None) -> Settings:
    config = configparser.ConfigParser(interpolation=None)
    loaded_files = config.read(config_path)
    if not loaded_files:
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {config_path}")
    if "GERAL" not in config:
        raise ValueError("O arquivo de configuração precisa conter a seção [GERAL].")

    general = config["GERAL"]
    base_dir = config_path.resolve().parent

    zabbix_url = _resolve_value(general.get("ZABBIX_URL", ""), "ZABBIX_URL").rstrip("/")
    username = _resolve_value(general.get("USERNAME", ""), "ZABBIX_USERNAME")
    password = _resolve_value(general.get("PASSWORD", ""), "ZABBIX_PASSWORD")
    from_time, to_time = _period_from_config(general)

    if not zabbix_url:
        raise ValueError("ZABBIX_URL não foi informado.")
    if not username:
        raise ValueError("USERNAME ou ZABBIX_USERNAME não foi informado.")
    if not password:
        raise ValueError("PASSWORD ou ZABBIX_PASSWORD não foi informado.")

    filters_by_page: dict[str, list[dict[str, str]]] = defaultdict(list)
    for section_name in config.sections():
        if section_name == "GERAL":
            continue
        section = config[section_name]
        page_name = section.get("pagina", "OUTROS").strip() or "OUTROS"
        filters_by_page[page_name].append(
            {
                "TEMPLATE_NAME": section.get("TEMPLATE_NAME", "").strip(),
                "TRIGGER_NAME": section.get("TRIGGER_NAME", "").strip(),
                "TEMPLATE_GROUP_NAME": section.get("TEMPLATE_GROUP_NAME", "").strip(),
                "HOSTGROUP_NAME": section.get("HOSTGROUP_NAME", "").strip(),
            }
        )

    max_attempts = cli_max_attempts or general.getint("MAX_ATTEMPTS", fallback=3)
    if max_attempts < 1:
        raise ValueError("MAX_ATTEMPTS precisa ser maior ou igual a 1.")

    retry_delay_seconds = general.getint("RETRY_DELAY_SECONDS", fallback=60)
    if retry_delay_seconds < 0:
        raise ValueError("RETRY_DELAY_SECONDS não pode ser negativo.")

    retry_backoff = general.getfloat("RETRY_BACKOFF", fallback=2.0)
    if retry_backoff < 1:
        raise ValueError("RETRY_BACKOFF precisa ser maior ou igual a 1.")

    return Settings(
        zabbix_url=zabbix_url,
        username=username,
        password=password,
        from_time=from_time,
        to_time=to_time,
        filters=dict(filters_by_page),
        output_dir=_resolve_path(general.get("OUTPUT_DIR", "reports"), base_dir),
        log_dir=_resolve_path(general.get("LOG_DIR", "logs"), base_dir),
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        retry_backoff=retry_backoff,
        log_level=general.get("LOG_LEVEL", "INFO").upper(),
    )


def configure_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S%z",
    )

    file_handler = RotatingFileHandler(
        log_dir / "service.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logger.level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logger.level)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


# === INTERAÇÃO COM O ZABBIX ===

async def login(page, url: str, user: str, password: str) -> None:
    await page.goto(url)
    await page.fill('input[name="name"]', user)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')
    await page.wait_for_selector("text=Dashboard")


async def select_zselect_value(page, zselect_name: str, partial_text: str):
    await page.click(f'z-select[name="{zselect_name}"] > button')
    await page.wait_for_timeout(300)

    items = await page.query_selector_all(f'z-select[name="{zselect_name}"] li')
    for item in items:
        title = await item.get_attribute("title")
        value = await item.get_attribute("value")
        if title and partial_text.lower() in title.lower():
            await item.click()
            await page.wait_for_timeout(1000)
            return value
    return None


async def select_template_and_trigger(page, template_name: str, trigger_name: str):
    template_id = await select_zselect_value(page, "filter_templateid", template_name)
    await page.wait_for_timeout(500)
    await page.click('z-select[name="tpl_triggerid"] > button')
    await page.wait_for_timeout(300)

    trigger_items = await page.query_selector_all('z-select[name="tpl_triggerid"] li')
    for item in trigger_items:
        title = await item.get_attribute("title")
        value = await item.get_attribute("value")
        if title and trigger_name.lower() in title.lower():
            return template_id, value
    return template_id, None


async def build_report_url(
    page, base_url: str, filtro: dict[str, str], from_time: str, to_time: str
) -> str:
    await page.goto(f"{base_url}/report2.php?action=availability.view")

    query = {
        "mode": "1",
        "from": from_time,
        "to": to_time,
        "filter_set": "1",
    }

    group_id = await select_zselect_value(page, "filter_groupid", filtro["TEMPLATE_GROUP_NAME"])
    hostgroup_id = await select_zselect_value(page, "hostgroupid", filtro["HOSTGROUP_NAME"])
    template_id, trigger_id = await select_template_and_trigger(
        page, filtro["TEMPLATE_NAME"], filtro["TRIGGER_NAME"]
    )

    selections = {
        "TEMPLATE_GROUP_NAME": (filtro["TEMPLATE_GROUP_NAME"], group_id),
        "HOSTGROUP_NAME": (filtro["HOSTGROUP_NAME"], hostgroup_id),
        "TEMPLATE_NAME": (filtro["TEMPLATE_NAME"], template_id),
        "TRIGGER_NAME": (filtro["TRIGGER_NAME"], trigger_id),
    }
    missing = [name for name, (expected, selected) in selections.items() if expected and not selected]
    if missing:
        raise ValueError(
            "Filtro(s) não localizado(s) no Zabbix: " + ", ".join(missing)
        )

    if group_id:
        query["filter_groupid"] = group_id
    if template_id:
        query["filter_templateid"] = template_id
    if trigger_id:
        query["tpl_triggerid"] = trigger_id
    if hostgroup_id:
        query["hostgroupid"] = hostgroup_id

    query_string = urlencode(query, quote_via=quote_plus)
    return f"{base_url}/report2.php?{query_string}"


async def extract_paginated_table(page, base_url: str, logger: logging.Logger) -> pd.DataFrame:
    await page.wait_for_selector("main > table")
    header_cells = await page.query_selector_all("main > table thead tr th")
    headers = [await cell.inner_text() for cell in header_cells]

    all_data = []
    current_page = 1

    while True:
        logger.info("Extraindo página %s", current_page)
        await page.wait_for_selector("main > table tbody tr")
        rows = await page.query_selector_all("main > table tbody tr")
        for row in rows:
            cols = await row.query_selector_all("td")
            if cols:
                all_data.append([await col.inner_text() for col in cols])

        next_link = await page.query_selector(
            'div.table-paging a[aria-label^="Ir para a próxima página"]'
        )
        if not next_link:
            break

        href = await next_link.get_attribute("href")
        if not href or "page=" not in href:
            break

        current_page += 1
        next_url = f"{base_url}/{href}"
        await page.goto(next_url)
        await page.wait_for_timeout(1000)

    return pd.DataFrame(all_data, columns=headers)


def ajustar_coluna_ok(df: pd.DataFrame) -> pd.DataFrame:
    if "Ok" in df.columns:
        df["Ok"] = df["Ok"].str.replace(".", "", regex=False).str.replace("%", "", regex=False)
    return df


async def run_once(settings: Settings, logger: logging.Logger) -> Path:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Iniciando coleta | período: %s até %s | grupos: %s",
        settings.from_time,
        settings.to_time,
        len(settings.filters),
    )

    browser = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            await login(page, settings.zabbix_url, settings.username, settings.password)
            logger.info("Login no Zabbix realizado com sucesso")

            results = {}
            for page_name, filters in settings.filters.items():
                complete_df = pd.DataFrame()
                for index, filtro in enumerate(filters, start=1):
                    logger.info(
                        "Aba [%s] | filtro %s/%s",
                        page_name,
                        index,
                        len(filters),
                    )
                    url = await build_report_url(
                        page,
                        settings.zabbix_url,
                        filtro,
                        settings.from_time,
                        settings.to_time,
                    )
                    await page.goto(url)
                    df = await extract_paginated_table(page, settings.zabbix_url, logger)
                    complete_df = pd.concat(
                        [complete_df, ajustar_coluna_ok(df)], ignore_index=True
                    )
                results[page_name] = complete_df

            filename = settings.output_dir / (
                f"relatorio_zabbix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            )
            with pd.ExcelWriter(filename, engine="openpyxl") as writer:
                for page_name, df in results.items():
                    df.to_excel(writer, sheet_name=page_name[:31], index=False)

            logger.info("Execução concluída com sucesso | arquivo: %s", filename)
            return filename
    finally:
        if browser is not None:
            await browser.close()


async def run_with_retries(settings: Settings, logger: logging.Logger) -> int:
    for attempt in range(1, settings.max_attempts + 1):
        try:
            await run_once(settings, logger)
            return 0
        except Exception:
            logger.exception(
                "Falha na execução | tentativa %s/%s",
                attempt,
                settings.max_attempts,
            )
            if attempt == settings.max_attempts:
                logger.error(
                    "Execução encerrada após %s tentativa(s) sem sucesso.",
                    settings.max_attempts,
                )
                return 1

            delay = int(
                settings.retry_delay_seconds * settings.retry_backoff ** (attempt - 1)
            )
            logger.warning(
                "Nova tentativa em %s segundo(s).",
                delay,
            )
            await asyncio.sleep(delay)

    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera relatório de disponibilidade do Zabbix.")
    parser.add_argument(
        "--config",
        default=os.getenv("ZABBIX_CONFIG", "config.ini"),
        help="Caminho do arquivo de configuração (padrão: config.ini).",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="Sobrescreve MAX_ATTEMPTS apenas nesta execução.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()

    try:
        settings = load_settings(config_path, cli_max_attempts=args.max_attempts)
    except Exception:
        fallback_logger = configure_logging(Path.cwd() / "logs")
        fallback_logger.exception("Não foi possível carregar a configuração: %s", config_path)
        return 1

    logger = configure_logging(settings.log_dir, settings.log_level)
    logger.info("Início do serviço | configuração: %s", config_path)
    exit_code = asyncio.run(run_with_retries(settings, logger))
    logger.info("Fim do serviço | código de saída: %s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
