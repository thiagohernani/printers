import requests

BASE = "https://www.selbetti.com.br/SmartManagerAPI/api"


def login(user, password):
    r = requests.post(f"{BASE}/user/validateaccess", json={"user": user, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]


def get_ticket_status(token, ticket_code):
    headers = {"sessionId": token}
    r = requests.get(f"{BASE}/Ticket/GetTicket", headers=headers, params={"ticketCode": ticket_code}, timeout=20)
    r.raise_for_status()
    t = r.json()["ticket"]
    return {
        "fornecedor": "Selbetti",
        "numero_ticket": t["ticketCode"],
        "status": t["status"],
        "sn": t.get("serialNumber"),
        "equipamento": t.get("equipmentModel"),
        "abertura": t.get("openingDate"),
        "prioridade": t.get("priority"),
        "sla_vencido": bool(t.get("slaExpired")),
        "descricao": t.get("problemDescription"),
    }
