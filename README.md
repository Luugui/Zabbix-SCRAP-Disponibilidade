# Relatório automático de disponibilidade do Zabbix

Este projeto extrai relatórios de disponibilidade do Zabbix, aplica filtros por template, trigger e hostgroup e gera um arquivo Excel com uma aba para cada valor de `pagina` configurado.

A execução foi preparada para funcionar como um serviço diário: as credenciais podem vir de variáveis de ambiente, o período pode ser automaticamente definido como o dia anterior, falhas transitórias geram novas tentativas com espera progressiva, e cada execução fica registrada em log.

## O que foi acrescentado

- **Retentativas automáticas:** por padrão são feitas até três tentativas, com espera de 60, 120 e 240 segundos entre elas. Os valores podem ser ajustados em `config.ini`.
- **Logs persistentes:** saída em `logs/service.log`, com rotação automática ao atingir 10 MB e retenção dos cinco arquivos anteriores. A mesma informação também aparece no console.
- **Período diário:** `PERIOD_MODE = previous_day` coleta o dia anterior completo. Para um intervalo fixo, use `PERIOD_MODE = configured` e preencha `FROM` e `TO`.
- **Saída organizada:** relatórios são gravados em `reports/` com data e hora no nome.
- **Código de saída confiável:** a execução retorna `0` apenas quando o Excel é gerado; depois da última tentativa sem sucesso retorna `1`.
- **Validação dos filtros:** template, trigger e grupos não localizados no Zabbix geram erro; assim o serviço não cria silenciosamente um relatório sem o filtro esperado.
- **Agendamento Linux pronto:** `deploy/zabbix-report.timer` agenda a execução diária e `deploy/zabbix-report.service` executa o coletor.
- **Credenciais fora do Git:** a configuração de exemplo usa `ZABBIX_USERNAME` e `ZABBIX_PASSWORD`; o arquivo de ambiente não deve ser versionado.

## Requisitos

- Python 3.9+
- Chromium compatível com Playwright
- Dependências Python:

```bash
pip install -r requirements.txt
playwright install chromium
```

Em um servidor Linux, prefira o instalador automatizado descrito abaixo, pois ele também prepara o ambiente do navegador.

## Configuração

Edite `config.ini` para informar a URL e os filtros. A configuração inicial já está preparada para execução diária:

```ini
[GERAL]
ZABBIX_URL = https://zabbix.exemplo.local/zabbix
USERNAME = env:ZABBIX_USERNAME
PASSWORD = env:ZABBIX_PASSWORD
PERIOD_MODE = previous_day
OUTPUT_DIR = reports
LOG_DIR = logs
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 60
RETRY_BACKOFF = 2
LOG_LEVEL = INFO
```

As credenciais podem ser fornecidas no shell:

```bash
export ZABBIX_USERNAME="Admin"
export ZABBIX_PASSWORD="senha-segura"
python zbx-report.py
```

Também é possível usar `${NOME_DA_VARIAVEL}` ou informar credenciais diretamente no arquivo, embora a última opção não seja recomendada quando o projeto estiver em um repositório.

### Período da coleta

Para coletar sempre o dia anterior, mantenha:

```ini
PERIOD_MODE = previous_day
```

Para preservar um intervalo específico, use:

```ini
PERIOD_MODE = configured
FROM = 2025-07-01 00:00:00
TO = 2025-07-16 23:59:59
```

## Execução manual

```bash
python zbx-report.py --config config.ini
```

Para testar uma quantidade menor de tentativas sem alterar o arquivo:

```bash
python zbx-report.py --config config.ini --max-attempts 1
```

## Instalação como serviço Linux

Os arquivos de implantação estão em `deploy/`. A instalação abaixo cria um usuário sem shell, instala o projeto em `/opt/zabbix-report`, prepara o ambiente Python e ativa o timer diário.

### Instalação automatizada

Execute na máquina Linux definitiva, a partir da raiz deste projeto, como `root` ou usando `sudo`:

```bash
sudo ./deploy/install-systemd.sh
```

Antes de iniciar a primeira coleta, edite as credenciais:

```bash
sudoedit /etc/zabbix-report/zabbix-report.env
sudo chmod 600 /etc/zabbix-report/zabbix-report.env
```

O horário padrão é **06:00 todos os dias**, de acordo com o fuso horário do servidor. Para alterar, edite `OnCalendar` em `deploy/zabbix-report.timer`, copie o arquivo para `/etc/systemd/system/`, execute `systemctl daemon-reload` e reinicie o timer.

### Comandos de operação

```bash
# Ver quando será a próxima execução
systemctl list-timers zabbix-report.timer

# Executar imediatamente, sem esperar o horário
sudo systemctl start zabbix-report.service

# Acompanhar o log do serviço
sudo journalctl -u zabbix-report.service -f

# Consultar o log detalhado gerado pelo programa
sudo tail -f /opt/zabbix-report/logs/service.log

# Verificar o último estado
systemctl status zabbix-report.service
```

O `systemd` mantém o agendamento após reinicializações (`Persistent=true`). O retry interno trata falhas transitórias, e `Restart=on-failure` cobre encerramentos inesperados do processo.

## Alternativas de operação

| Abordagem | Tradeoffs | Custo | Complexidade de instalação |
|---|---|---:|---:|
| **Servidor Linux com `systemd` e os arquivos deste projeto** | Roda independentemente do computador do usuário, mantém logs e reinicia após falhas; exige um servidor Linux disponível | Depende do servidor | Média |
| **Computador local com `cron` (Linux/macOS) ou Agendador de Tarefas (Windows)** | Não exige servidor adicional, mas a máquina precisa estar ligada, conectada ao Zabbix e com o ambiente Python instalado no horário | Sem custo adicional | Baixa a média |
| **Execução manual** | Útil para validação e diagnóstico, mas não garante coleta diária | Sem custo adicional | Baixa |

Para produção, escolha entre as duas primeiras conforme a disponibilidade do ambiente: o código e os mecanismos de retry/log são os mesmos.

## Estrutura

```text
.
├── config.ini
├── deploy/
│   ├── install-systemd.sh
│   ├── zabbix-report.env.example
│   ├── zabbix-report.service
│   └── zabbix-report.timer
├── requirements.txt
├── zbx-report.py
├── logs/       # criado na primeira execução; ignorado pelo Git
└── reports/    # criado na primeira execução; ignorado pelo Git
```

## Observações técnicas

- Os filtros são aplicados usando nomes parciais nos componentes `z-select` do Zabbix.
- A paginação do relatório é percorrida automaticamente até o fim.
- A coluna `Ok`, quando presente, tem pontos e `%` removidos conforme o comportamento original.
- Nomes de abas são limitados a 31 caracteres, conforme a limitação do Excel.
- O arquivo final só é considerado uma execução bem-sucedida quando a gravação do Excel termina sem exceção.
