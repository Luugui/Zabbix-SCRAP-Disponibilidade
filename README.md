# 📊 Zabbix Relatório Automático

Este script automatiza a extração de relatórios de disponibilidade do Zabbix, aplicando filtros dinâmicos por template, trigger e hostgroup. Os dados são organizados e exportados automaticamente para um arquivo Excel com múltiplas abas.

---

## ✅ Funcionalidades

- Login automático no Zabbix
- Extração de relatórios do `report2.php`
- Aplicação de filtros baseados em nomes (não IDs)
- Suporte à paginação de resultados
- Exportação para Excel (.xlsx) com várias abas
- Leitura de parâmetros por arquivo `config.ini`

---

## 📦 Requisitos

- Python 3.9+
- Dependências:

```bash
pip install -r requirements.txt
playwright install chromium
```
---

## 📁 Estrutura esperada do projeto
```arduino
zbx-report/
├── zbx-report.py
├── config.ini
├── requirements.txt
└── README.md
```

---

## 🧾 Exemplo de config.ini
```ini
[GERAL]
ZABBIX_URL = https://127.0.0.1/zabbix
USERNAME = Admin
PASSWORD = zabbix
FROM = 2025-07-01 00:00:00
TO = 2025-07-16 23:59:59

[CONJUNTO_1]
pagina = SERVIDORES
TEMPLATE_NAME = ICMP Ping
TRIGGER_NAME = ICMP: Unavailable by ICMP ping
TEMPLATE_GROUP_NAME = Infraestrutura
HOSTGROUP_NAME = Servidores

[CONJUNTO_2]
pagina = REDES
TEMPLATE_NAME = Ping Router
TRIGGER_NAME = Router Offline
TEMPLATE_GROUP_NAME = Core
HOSTGROUP_NAME = Infraestrutura
```
Todas as seções com o mesmo valor de pagina serão agrupadas na mesma aba do Excel.

---

## ▶️ Como executar
### 1. Instale as dependências
```bash
pip install -r requirements.txt
playwright install chromium
```
### 2. Execute o script
```bash
python zbx-report.py
```
### 3. Resultado
Um arquivo como:
```

relatorio_zabbix_20250717_134512.xlsx
```
Será salvo na mesma pasta do script, com uma aba para cada pagina definida no config.ini.

---

## 🔧 Observações Técnicas
- Os filtros são aplicados usando nomes parciais (não IDs) com z-select.
- A coluna OK, se presente, terá os pontos e % removidos (ex: 98.5200% → 985200).
- A paginação do Zabbix é percorrida automaticamente até o fim.
- Nomes de abas do Excel são limitados a 31 caracteres.


