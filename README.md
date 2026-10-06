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

---

## 🖥️ ZBX Sender — aplicativo desktop

O repositório também inclui um pequeno aplicativo em **Python + CustomTkinter**
para enviar um único valor a um item **trapper** do Zabbix usando a biblioteca
oficial `zabbix_utils`.

### Funcionalidades

- Interface escura, moderna e minimalista.
- Campos para servidor, porta, host, chave do item e valor.
- Tipos de valor numérico ou texto, com suporte a decimal usando vírgula.
- Timestamp opcional no formato `AAAA-MM-DD HH:MM:SS` ou epoch.
- Atalho `Ctrl + Enter` para envio rápido.
- Histórico local dos envios em JSON.
- Prévia da chamada nativa `Sender.send_value`.
- Timeout configurável diretamente na biblioteca oficial.
- Comunicação direta com o protocolo Sender, sem `zabbix_sender` externo.

### Como executar em modo desenvolvimento

```bash
python -m pip install -r requirements-sender.txt
python zbx_sender_app.py
```

O pacote `zabbix_utils` é instalado automaticamente e implementa o protocolo
Sender diretamente em Python. A biblioteca oficial é compatível com Zabbix 6.0+
e Python 3.8+. Consulte a [documentação oficial do Sender em Python](https://www.zabbix.com/documentation/7.4/en/devel/python/sender)
e o [repositório oficial da biblioteca](https://github.com/zabbix/python-zabbix-utils)
para detalhes da API.

### Como gerar o executável

Linux:

```bash
./build_linux.sh
```

Windows PowerShell:

```powershell
.\build_windows.ps1
```

O artefato será criado na pasta `dist/`. O binário do aplicativo já inclui o
CustomTkinter e o `zabbix_utils`; nenhum executável externo do Zabbix é
necessário no computador de destino.

### Observação sobre TLS

O `zabbix_utils` oficial não oferece TLS pronto no `Sender`. Para ambientes que
exigem criptografia PSK ou certificado, é necessário fornecer um `socket_wrapper`
com uma biblioteca TLS compatível. Essa opção ainda não está exposta na tela
do aplicativo.
