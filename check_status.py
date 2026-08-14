import csv
import json
import os
import re
import sys
from datetime import datetime

import config
import jira_client
import selbetti_client
from simpress_client import SimpressSession

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "tickets.csv")
DATA_JS_PATH = os.path.join(BASE_DIR, "data.js")


DIAS_SEM_RESPOSTA_ATRASA = 30


def _dias_aberto(abertura):
    if not abertura:
        return None
    try:
        data_abertura = datetime.fromisoformat(abertura)
    except ValueError:
        return None
    return (datetime.now() - data_abertura).days


def classify(status, sla_vencido=False, abertura=None):
    s = (status or "").upper()
    if any(k in s for k in ["FINALIZ", "CONCLU", "ENCERRAD", "RESOLVID", "ENTREGUE"]):
        return "verde"
    if "CANCELAD" in s:
        return "cinza"
    if sla_vencido or "ATRAS" in s:
        return "vermelho"
    if s in ("", "NAO ENCONTRADO"):
        return "cinza"
    dias = _dias_aberto(abertura)
    if dias is not None and dias >= DIAS_SEM_RESPOSTA_ATRASA:
        return "vermelho"
    return "amarelo"


def load_tickets(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def field(row, key):
    return (row.get(key) or "").strip()


def _ticket_digits(numero):
    return re.sub(r"\D", "", str(numero or ""))


def load_resolved_cache():
    """Tickets ja confirmados como resolvidos na ultima checagem - nao precisam
    ser consultados de novo, ja que dificilmente um chamado reabre."""
    if not os.path.exists(DATA_JS_PATH):
        return {}
    try:
        with open(DATA_JS_PATH, encoding="utf-8") as f:
            content = f.read()
        json_part = content[len("const TICKETS_DATA = "):].strip().rstrip(";")
        payload = json.loads(json_part)
    except Exception:
        return {}
    cache = {}
    for t in payload.get("tickets", []):
        if t.get("cor") == "verde":
            key = (str(t.get("fornecedor", "")).lower(), _ticket_digits(t.get("numero_ticket")))
            cache[key] = t
    return cache


def build_payload():
    errors = []
    resolved_cache = load_resolved_cache()

    try:
        jira_rows, jira_warnings = jira_client.fetch_tracked_tickets(config.JIRA_URL, config.JIRA_EMAIL, config.JIRA_TOKEN)
        errors.extend(jira_warnings)
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

    def cached_result(r, fornecedor_key):
        cache_key = (fornecedor_key, _ticket_digits(field(r, "numero_ticket")))
        cached = resolved_cache.get(cache_key)
        if not cached:
            return None
        info = dict(cached)
        info["chamado_interno"] = field(r, "chamado_interno")
        info["motivo"] = field(r, "motivo") or info.get("motivo", "")
        return info

    selbetti_to_check = []
    for r in selbetti_rows:
        cached = cached_result(r, "selbetti")
        if cached:
            results.append(cached)
        else:
            selbetti_to_check.append(r)

    simpress_to_check = []
    for r in simpress_rows:
        cached = cached_result(r, "simpress")
        if cached:
            results.append(cached)
        else:
            simpress_to_check.append(r)

    reused_from_cache = len(results)

    if selbetti_to_check:
        try:
            token = selbetti_client.login(config.SELBETTI_USER, config.SELBETTI_PASS)
            for r in selbetti_to_check:
                try:
                    info = selbetti_client.get_ticket_status(token, field(r, "numero_ticket"))
                    info["chamado_interno"] = field(r, "chamado_interno")
                    info["motivo"] = field(r, "motivo")
                    info["cor"] = classify(info["status"], info.get("sla_vencido"), info.get("abertura"))
                    results.append(info)
                except Exception as e:
                    errors.append(f"Selbetti #{field(r, 'numero_ticket')}: {e}")
        except Exception as e:
            errors.append(f"Login Selbetti falhou: {e}")

    if simpress_to_check:
        try:
            with SimpressSession(config.SIMPRESS_USER, config.SIMPRESS_PASS) as session:
                for r in simpress_to_check:
                    try:
                        info = session.get_ticket_status(field(r, "numero_ticket"))
                        info["chamado_interno"] = field(r, "chamado_interno")
                        info["motivo"] = field(r, "motivo")
                        info["cor"] = classify(info["status"], info.get("sla_vencido"), info.get("abertura"))
                        results.append(info)
                    except Exception as e:
                        errors.append(f"Simpress #{field(r, 'numero_ticket')}: {e}")
        except Exception as e:
            errors.append(f"Login Simpress falhou: {e}")

    return {
        "atualizado_em": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "tickets": results,
        "erros": errors,
        "reaproveitados_do_cache": reused_from_cache,
    }


def write_data_js(payload):
    with open(DATA_JS_PATH, "w", encoding="utf-8") as f:
        f.write("const TICKETS_DATA = ")
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(";\n")


def main():
    payload = build_payload()
    write_data_js(payload)
    checados = len(payload["tickets"]) - payload["reaproveitados_do_cache"]
    print(
        f"{len(payload['tickets'])} ticket(s) no total - {checados} consultado(s) agora, "
        f"{payload['reaproveitados_do_cache']} ja resolvido(s) reaproveitado(s) do cache. "
        f"{len(payload['erros'])} erro(s)."
    )
    for e in payload["erros"]:
        print("  ERRO:", e)


if __name__ == "__main__":
    sys.exit(main())
