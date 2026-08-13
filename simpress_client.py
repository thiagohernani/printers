import json
from datetime import date, timedelta
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://ux.simpress.com.br/ng/autenticacao/login"
TICKET_SEARCH_URL = "https://apiexterno.simpress.com.br/camadadeservico/servicedesk/v2/apontamentos/consulta"
OS_SEARCH_URL = "https://apiexterno.simpress.com.br/camadadeservico/servicos/v1/solicitacoesatendimento/consulta"
CLIENT_ID = "f84d3d5d-b173-32a0-8610-8b02c6116b74"
APP_TOKEN = "6768b72b-5e89-4f24-84a2-89cfca2cead0"


class SimpressSession:
    def __init__(self, user, password, attempts=2):
        self._pw = sync_playwright().start()
        self._browser = None
        self.page = None
        last_error = None
        for _ in range(attempts):
            try:
                self._login(user, password)
                return
            except Exception as e:
                last_error = e
                if self._browser:
                    self._browser.close()
                    self._browser = None
        self._pw.stop()
        raise RuntimeError(f"Login na Simpress falhou: {last_error}")

    def _login(self, user, password):
        self._browser = self._pw.chromium.launch(headless=True)
        self.page = self._browser.new_page(viewport={"width": 1400, "height": 900})
        self.page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
        self.page.wait_for_timeout(1000)
        self.page.locator("#inputEmail input").fill(user)
        self.page.locator("#inputSenha input").fill(password)
        self.page.locator("#inputSenha input").press("Enter")
        self.page.wait_for_timeout(6000)
        if "login" in self.page.url:
            raise RuntimeError("credenciais invalidas ou portal lento demais para responder")

    def close(self):
        self._browser.close()
        self._pw.stop()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def get_ticket_status(self, ticket_number):
        # numeros de ticket (ex: CS0246980) e numeros de Ordem de Servico (ex: 7127827)
        # sao duas APIs diferentes no portal da Simpress; detecta pelo formato.
        if ticket_number.strip().upper().startswith("CS"):
            return self._search_ticket(ticket_number)
        return self._search_os(ticket_number)

    def _search_ticket(self, ticket_number):
        resp = self.page.request.post(
            TICKET_SEARCH_URL,
            headers={
                "client_id": CLIENT_ID,
                "app_token": APP_TOKEN,
                "content-type": "application/json",
            },
            data=json.dumps({
                "apontamentoTickets": [ticket_number],
                "numerosSerie": "",
                "status": 0,
                "dataFim": date.today().isoformat(),
                "dataIni": (date.today() - timedelta(days=365)).isoformat(),
                "Pagina": 1,
                "RegistrosPorPagina": 10,
            }),
        )
        body = resp.json()
        dados = body.get("dados", [])
        if not dados:
            return {
                "fornecedor": "Simpress",
                "numero_ticket": ticket_number,
                "status": "NAO ENCONTRADO",
                "sn": None,
                "abertura": None,
                "sla_vencido": False,
            }
        t = dados[0]
        return {
            "fornecedor": "Simpress",
            "numero_ticket": t.get("numeroTicket"),
            "status": t.get("status"),
            "sn": t.get("numeroSerie"),
            "abertura": t.get("dataAbertura"),
            "sla_vencido": False,
        }

    def _search_os(self, os_number):
        resp = self.page.request.post(
            OS_SEARCH_URL,
            headers={
                "client_id": CLIENT_ID,
                "app_token": APP_TOKEN,
                "content-type": "application/json",
            },
            data=json.dumps({
                "contrato": None,
                "alias": None,
                "status": None,
                "cep": None,
                "codOS": os_number,
                "dataInicial": (date.today() - timedelta(days=365)).isoformat(),
                "dataFinal": date.today().isoformat(),
                "idEquipamento": None,
                "usuarioInclusao": 0,
                "nomeUsuarioOuEmail": "",
                "OSReabertas": 0,
                "TipoAcionamento": None,
            }),
        )
        dados = resp.json()
        if not dados:
            return {
                "fornecedor": "Simpress",
                "numero_ticket": os_number,
                "status": "NAO ENCONTRADO",
                "sn": None,
                "abertura": None,
                "sla_vencido": False,
            }
        t = dados[0]
        status = (t.get("status") or "").strip()
        prazo = t.get("dataPrazo")
        sla_vencido = False
        if prazo and "FINALIZ" not in status.upper():
            sla_vencido = date.fromisoformat(prazo[:10]) < date.today()
        return {
            "fornecedor": "Simpress",
            "numero_ticket": f"OS {t.get('codOS')}",
            "status": status,
            "sn": t.get("numeroSerie"),
            "abertura": t.get("dataAbertura"),
            "sla_vencido": sla_vencido,
        }
