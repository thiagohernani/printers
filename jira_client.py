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
