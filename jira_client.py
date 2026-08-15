import re
import requests
from requests.auth import HTTPBasicAuth

JQL = 'project = "IS" AND assignee = currentUser() AND statusCategory != Done ORDER BY created DESC'
OS_RE = re.compile(r'OS\s*(\d{6,9})')


def _detect_fornecedor(summary):
    s = summary.lower()
    if "simp" in s:
        return "Simpress"
    if "selb" in s:
        return "Selbetti"
    return None


def fetch_tracked_tickets(jira_url, email, token):
    auth = HTTPBasicAuth(email, token)
    issues = []
    next_token = None
    while True:
        body = {"jql": JQL, "maxResults": 100, "fields": ["summary", "status"]}
        if next_token:
            body["nextPageToken"] = next_token
        r = requests.post(
            f"{jira_url}/rest/api/3/search/jql",
            auth=auth,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=body,
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        issues.extend(data.get("issues", []))
        next_token = data.get("nextPageToken")
        if not next_token or data.get("isLast", True):
            break

    tickets = []
    warnings = []
    for issue in issues:
        summary = issue["fields"]["summary"]
        m = OS_RE.search(summary)
        if not m:
            continue
        fornecedor = _detect_fornecedor(summary)
        if not fornecedor:
            warnings.append(
                f"{issue['key']}: tem 'OS {m.group(1)}' no titulo mas nao diz o fornecedor "
                f"(Simpress ou Selbetti) - ticket ignorado, corrija o titulo no Jira"
            )
            continue
        tickets.append({
            "fornecedor": fornecedor,
            "numero_ticket": m.group(1),
            "motivo": summary.split("|")[0].strip(),
            "chamado_interno": issue["key"],
        })
    return tickets, warnings


RESOLUTION_ID_FECHAMENTO_AUTOMATICO = "12242"  # "With technical intervention"

MENSAGEM_ENCERRAMENTO = """Informamos que o chamado foi analisado e as tratativas necessárias foram realizadas. No momento, não foram identificadas pendências relacionadas à solicitação.

Dessa forma, estamos realizando o encerramento deste chamado. Caso o problema persista ou surja qualquer nova dúvida, pedimos a gentileza de abrir um novo chamado para que possamos auxiliá-lo novamente.

Sua opinião é muito importante para nós. Pedimos, por gentileza, que avalie este atendimento com 5 estrelas ⭐⭐⭐⭐⭐ caso tenha ficado satisfeito.

Agradecemos o contato e permanecemos à disposição."""


def _adf(texto):
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": texto}]}],
    }


def close_ticket(jira_url, email, token, issue_key, status_text):
    """Fecha o chamado no Jira (transicao 'Resolve'), reaproveitando os campos
    que ja vem preenchidos no proprio chamado (Incident type, IS Ubicacion,
    responsavel) e preenchendo Resolution/Solution. Tambem posta a mensagem de
    encerramento padrao como resposta publica ao cliente."""
    auth = HTTPBasicAuth(email, token)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    r = requests.get(
        f"{jira_url}/rest/api/3/issue/{issue_key}"
        "?fields=customfield_18629,customfield_18388,assignee",
        auth=auth, headers=headers, timeout=20,
    )
    r.raise_for_status()
    campos_atuais = r.json()["fields"]

    r2 = requests.get(
        f"{jira_url}/rest/api/3/issue/{issue_key}/transitions",
        auth=auth, headers=headers, timeout=20,
    )
    r2.raise_for_status()
    done_transition = next(
        (t for t in r2.json().get("transitions", []) if t["to"]["statusCategory"]["key"] == "done"),
        None,
    )
    if not done_transition:
        return False

    transition_body = {
        "transition": {"id": done_transition["id"]},
        "fields": {
            "resolution": {"id": RESOLUTION_ID_FECHAMENTO_AUTOMATICO},
            "customfield_12729": _adf(f"Fornecedor confirmou resolucao - status: {status_text}"),
        },
    }
    if campos_atuais.get("customfield_18629"):
        transition_body["fields"]["customfield_18629"] = campos_atuais["customfield_18629"]
    if campos_atuais.get("customfield_18388"):
        transition_body["fields"]["customfield_18388"] = campos_atuais["customfield_18388"]
    if campos_atuais.get("assignee"):
        transition_body["fields"]["assignee"] = {"accountId": campos_atuais["assignee"]["accountId"]}

    requests.post(
        f"{jira_url}/rest/servicedeskapi/request/{issue_key}/comment",
        auth=auth, headers=headers,
        json={"body": MENSAGEM_ENCERRAMENTO, "public": True},
        timeout=20,
    ).raise_for_status()

    requests.post(
        f"{jira_url}/rest/api/3/issue/{issue_key}/transitions",
        auth=auth, headers=headers, json=transition_body, timeout=20,
    ).raise_for_status()
    return True
