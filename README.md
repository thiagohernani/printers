# Chamados de Impressoras

Dashboard local que acompanha automaticamente o status dos chamados abertos
nos portais da **Selbetti** e da **Simpress**, cruzando com os chamados do
**Jira** (projeto IS) atribuídos a você.

Sem isso, o fluxo é manual: abrir cada portal, colar o número do ticket,
ver o status e atualizar o chamado do Jira à mão. Com isso, é um clique.

## Como funciona

1. O script consulta o Jira (`assignee = currentUser()`, projeto IS) e lê o
   **título** de cada chamado em aberto atribuído a você.
2. Se o título seguir o padrão `motivo | Fornecedor | OS numero` (ex:
   `Impressora não liga | Simpress | OS 7127827`), ele extrai o fornecedor e
   o número do ticket automaticamente. Também funciona sem o nome do
   fornecedor explícito, inferindo pelo formato do número (Simpress = 7
   dígitos começando com `7`; Selbetti = 8 dígitos começando com `14`).
3. Para cada ticket encontrado, consulta a API do fornecedor correspondente
   e pega o status atual.
4. Gera `data.js`, que alimenta o `dashboard.html` — cartões coloridos por
   situação (verde = resolvido, amarelo = em andamento, vermelho = atrasado),
   com busca, filtros e link direto pro chamado no Jira.
5. Chamados registrados manualmente em `tickets.csv` (colunas
   `fornecedor,numero_ticket,motivo`) também entram na lista, além dos que
   vêm do Jira - útil pra algo que não segue o padrão de título.

## Requisitos

- Python 3.10+ (testado em 3.14)
- Windows (os scripts de agendamento usam `schtasks` e atalhos do Windows;
  o resto do código é portável)

## Instalação

```
pip install playwright
python -m playwright install chromium
```

Copie `.env.example` para `.env` e preencha com as suas próprias
credenciais:

- `SELBETTI_USER` / `SELBETTI_PASS`: seu login no portal da Selbetti.
- `SIMPRESS_USER` / `SIMPRESS_PASS`: seu login no portal da Simpress.
- `JIRA_EMAIL`: seu e-mail da conta Atlassian.
- `JIRA_TOKEN`: token pessoal gerado em
  https://id.atlassian.com/manage-profile/security/api-tokens (dá pra
  definir uma data de expiração longa, tipo 1 ano - quando vencer, gere
  outro e atualize o `.env`).

**Nunca** compartilhe o `.env` preenchido - ele é só seu, e fica fora do
controle de versão (`.gitignore` já cobre isso).

## Convenção no Jira

Para a leitura automática funcionar, o título do chamado no Jira precisa
mencionar o número do ticket do fornecedor no formato `OS <número>` em
algum ponto do resumo - é o que o relator ou você mesmo já costuma colocar
depois de abrir o chamado no portal do fornecedor. Não precisa ser
rigorosamente `motivo | Fornecedor | OS numero`; só ter `OS 1234567` em
algum lugar do título já basta.

## Uso

Rodar a checagem manualmente:

```
python check_status.py
```

Isso atualiza o `data.js`. Pra ver o resultado, abra `dashboard.html`
direto no navegador.

Pra usar o botão **"Atualizar agora"** dentro do dashboard (sem precisar
abrir terminal), rode o servidor local:

```
python server.py
```

E acesse **http://127.0.0.1:8743/** no navegador (em vez de abrir o
arquivo direto).

## Automação (opcional)

Duas coisas podem ser agendadas pra rodar sozinhas:

**1. Checagem diária** (atualiza `data.js` mesmo sem abrir o dashboard):

```
schtasks /Create /TN "ChamadosImpressoras_CheckStatus" /TR "\"<caminho para o python.exe>\" \"<caminho para check_status.py>\"" /SC DAILY /ST 08:00
```

**2. Servidor local iniciando sozinho no login do Windows**, pro botão
"Atualizar agora" já funcionar assim que você liga o PC. Se
`schtasks /SC ONLOGON` for bloqueado por política de grupo da empresa (foi
o nosso caso), a alternativa é um atalho na pasta Inicializar do Windows
(`shell:startup`) apontando pro `pythonw.exe` (sem janela de terminal) com
`server.py` como argumento.

## Estrutura

| Arquivo | O que é |
|---|---|
| `check_status.py` | Orquestra tudo: Jira + tickets.csv → consulta fornecedores → gera `data.js` |
| `jira_client.py` | Busca chamados no Jira e extrai fornecedor/ticket do título |
| `selbetti_client.py` | Cliente da API da Selbetti |
| `simpress_client.py` | Cliente da Simpress (login via navegador headless + API) |
| `server.py` | Servidor local que serve o dashboard e expõe o botão "Atualizar agora" |
| `dashboard.html` | Interface visual |
| `tickets.csv` | Tickets adicionados manualmente (opcional, além do Jira) |
| `config.py` | Carrega as credenciais do `.env` |
