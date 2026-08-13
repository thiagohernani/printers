import csv
import json
import os
import sys
from datetime import datetime

import config
import jira_client
import selbetti_client
from simpress_client import SimpressSession

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "tickets.csv")
DATA_JS_PATH = os.path.join(BASE_DIR, "data.js")


def classify(status, sla_vencido=False):
    s = (status or "").upper()
    if any(k in s for k in ["FINALIZ", "CONCLU", "ENCERRAD", "RESOLVID", "ENTREGUE"]):
        return "verde"
    if "CANCELAD" in s:
        return "cinza"
    if sla_vencido or "ATRAS" in s:
        return "vermelho"
    if s in ("", "NAO ENCONTRADO"):
        return "cinza"
    return "amarelo"


def load_tickets(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def field(row, key):
    return (row.get(key) or "").strip()


def build_payload():
    errors = []

    try:
        jira_rows = jira_client.fetch_tracked_tickets(config.JIRA_URL, config.JIRA_EMAIL, config.JIRA_TOKEN)
    except Exception as e:
        jira_rows = []
        errors.append(f"Busca no Jira falhou: {e}")

    csv_rows = load_tickets(CSV_PATH)
    csv_rows = [r for r in csv_rows if field(r, "numero_ticket")]

    seen = set()
    rows = []
    for r in jira_rows + csv_rows:
        key = (field(r, "fornecedor").lower(), field(r, "numero_ticket"))
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)

    results = []

    selbetti_rows = [r for r in rows if field(r, "fornecedor").lower() == "selbetti"]
    simpress_rows = [r for r in rows if field(r, "fornecedor").lower() == "simpress"]
    unknown_rows = [r for r in rows if field(r, "fornecedor").lower() not in ("selbetti", "simpress")]
    for r in unknown_rows:
        errors.append(
            f"Fornecedor '{field(r, 'fornecedor')}' (ticket #{field(r, 'numero_ticket')}) nao reconhecido - "
            f"use exatamente 'Selbetti' ou 'Simpress' no tickets.csv"
        )

    if selbetti_rows:
        try:
            token = selbetti_client.login(config.SELBETTI_USER, config.SELBETTI_PASS)
            for r in selbetti_rows:
                try:
                    info = selbetti_client.get_ticket_status(token, field(r, "numero_ticket"))
                    info["chamado_interno"] = field(r, "chamado_interno")
                    info["motivo"] = field(r, "motivo")
                    info["cor"] = classify(info["status"], info.get("sla_vencido"))
                    results.append(info)
                except Exception as e:
                    errors.append(f"Selbetti #{field(r, 'numero_ticket')}: {e}")
        except Exception as e:
            errors.append(f"Login Selbetti falhou: {e}")

    if simpress_rows:
        try:
            with SimpressSession(config.SIMPRESS_USER, config.SIMPRESS_PASS) as session:
                for r in simpress_rows:
                    try:
                        info = session.get_ticket_status(field(r, "numero_ticket"))
                        info["chamado_interno"] = field(r, "chamado_interno")
                        info["motivo"] = field(r, "motivo")
                        info["cor"] = classify(info["status"], info.get("sla_vencido"))
                        results.append(info)
                    except Exception as e:
                        errors.append(f"Simpress #{field(r, 'numero_ticket')}: {e}")
        except Exception as e:
            errors.append(f"Login Simpress falhou: {e}")

    return {
        "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "tickets": results,
        "erros": errors,
    }


def write_data_js(payload):
    with open(DATA_JS_PATH, "w", encoding="utf-8") as f:
        f.write("const TICKETS_DATA = ")
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(";\n")


def main():
    payload = build_payload()
    write_data_js(payload)
    print(f"{len(payload['tickets'])} ticket(s) atualizados, {len(payload['erros'])} erro(s).")
    for e in payload["erros"]:
        print("  ERRO:", e)


if __name__ == "__main__":
    sys.exit(main())
