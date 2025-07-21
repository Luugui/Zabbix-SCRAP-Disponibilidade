import asyncio
import pandas as pd
from urllib.parse import urlencode, quote_plus
from playwright.async_api import async_playwright
import configparser
from collections import defaultdict
from datetime import datetime

# === ZABBIX INTERAÇÃO ===

async def login(page, url, user, password):
    await page.goto(url)
    await page.fill('input[name="name"]', user)
    await page.fill('input[name="password"]', password)
    await page.click('button[type="submit"]')
    await page.wait_for_selector("text=Dashboard")

async def select_zselect_value(page, zselect_name, partial_text):
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

async def select_template_and_trigger(page, template_name, trigger_name):
    tpl_id = await select_zselect_value(page, "filter_templateid", template_name)
    await page.wait_for_timeout(500)
    await page.click('z-select[name="tpl_triggerid"] > button')
    await page.wait_for_timeout(300)

    trigger_items = await page.query_selector_all('z-select[name="tpl_triggerid"] li')
    for item in trigger_items:
        title = await item.get_attribute("title")
        value = await item.get_attribute("value")
        if title and trigger_name.lower() in title.lower():
            return tpl_id, value
    return tpl_id, None

async def build_report_url(page, base_url, filtro, from_time, to_time):
    await page.goto(f"{base_url}/report2.php?action=availability.view")
    
    mode = "1"
    query = {
        "mode": mode,
        "from": from_time,
        "to": to_time,
        "filter_set": "1"
    }

    group_id = await select_zselect_value(page, "filter_groupid", filtro["TEMPLATE_GROUP_NAME"])
    hostgroup_id = await select_zselect_value(page, "hostgroupid", filtro["HOSTGROUP_NAME"])
    tpl_id, trig_id = await select_template_and_trigger(page, filtro["TEMPLATE_NAME"], filtro["TRIGGER_NAME"])

    if group_id: query["filter_groupid"] = group_id
    if tpl_id: query["filter_templateid"] = tpl_id
    if trig_id: query["tpl_triggerid"] = trig_id
    if hostgroup_id: query["hostgroupid"] = hostgroup_id

    query_string = urlencode(query, quote_via=quote_plus)
    return f"{base_url}/report2.php?{query_string}"

async def extract_paginated_table(page, base_url):
    await page.wait_for_selector("main > table")
    header_cells = await page.query_selector_all("main > table thead tr th")
    headers = [await cell.inner_text() for cell in header_cells]

    all_data = []
    current_page = 1

    while True:
        print(f"📄 Página {current_page}")
        await page.wait_for_selector("main > table tbody tr")
        rows = await page.query_selector_all("main > table tbody tr")
        for row in rows:
            cols = await row.query_selector_all("td")
            if cols:
                all_data.append([await col.inner_text() for col in cols])

        next_link = await page.query_selector('div.table-paging a[aria-label^="Ir para a próxima página"]')
        if next_link:
            href = await next_link.get_attribute("href")
            if href and "page=" in href:
                current_page += 1
                next_url = f"{base_url}/{href}"
                await page.goto(next_url)
                await page.wait_for_timeout(1000)
            else:
                break
        else:
            break

    return pd.DataFrame(all_data, columns=headers)

def ajustar_coluna_ok(df):
    if "Ok" in df.columns:
        df["Ok"] = df["Ok"].str.replace(".", "", regex=False).str.replace("%", "", regex=False)
    return df


# === SCRIPT PRINCIPAL ===

async def main():
    config = configparser.ConfigParser()
    config.read("config.ini")

    geral = config["GERAL"]
    zabbix_url = geral.get("ZABBIX_URL")
    username = geral.get("USERNAME")
    password = geral.get("PASSWORD")
    from_time = geral.get("FROM")
    to_time = geral.get("TO")

    aba_por_pagina = defaultdict(list)

    for section in config.sections():
        if section == "GERAL":
            continue
        pagina = config[section].get("pagina", "OUTROS")
        filtro = {
            "TEMPLATE_NAME": config[section].get("TEMPLATE_NAME", ""),
            "TRIGGER_NAME": config[section].get("TRIGGER_NAME", ""),
            "TEMPLATE_GROUP_NAME": config[section].get("TEMPLATE_GROUP_NAME", ""),
            "HOSTGROUP_NAME": config[section].get("HOSTGROUP_NAME", "")
        }
        aba_por_pagina[pagina].append(filtro)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await login(page, zabbix_url, username, password)

        resultados = {}

        for aba, filtros in aba_por_pagina.items():
            df_completo = pd.DataFrame()
            for i, filtro in enumerate(filtros):
                print(f"\n📊 Aba [{aba}] - Filtro {i+1}")
                url = await build_report_url(page, zabbix_url, filtro, from_time, to_time)
                print(f"🔗 {url}")
                await page.goto(url)
                df = await extract_paginated_table(page, zabbix_url)
                df = ajustar_coluna_ok(df)
                df_completo = pd.concat([df_completo, df], ignore_index=True)
            resultados[aba] = df_completo

        filename = f"relatorio_zabbix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            for aba, df in resultados.items():
                df.to_excel(writer, sheet_name=aba[:31], index=False)

        print(f"\n✅ Arquivo salvo: {filename}")
        await browser.close()

asyncio.run(main())
