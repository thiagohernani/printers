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


def load_previous_tickets():
    """Estado da ultima checagem, indexado por (fornecedor, numero) - usado tanto
    para pular tickets ja resolvidos quanto para detectar quando um ticket acabou
    de mudar de status."""
    if not os.path.exists(DATA_JS_PATH):
        return {}
    try:
        with open(DATA_JS_PATH, encoding="utf-8") as f:
            content = f.read()
        json_part = content[len("const TICKETS_DATA = "):].strip().rstrip(";")
        payload = json.loads(json_part)
    except Exception:
        return {}
    previous = {}
    for t in payload.get("tickets", []):
        key = (str(t.get("fornecedor", "")).lower(), _ticket_digits(t.get("numero_ticket")))
        previous[key] = t
    return previous


def build_payload():
    errors = []
    previous_tickets = load_previous_tickets()
    resolved_cache = {k: t for k, t in previous_tickets.items() if t.get("cor") == "verde"}

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
        info["recem_resolvido"] = False
        return info

    def marcar_se_recem_resolvido(info, fornecedor_key, numero_ticket):
        prev = previous_tickets.get((fornecedor_key, _ticket_digits(numero_ticket)))
        prev_cor = prev.get("cor") if prev else None
        info["recem_resolvido"] = info["cor"] == "verde" and prev_cor is not None and prev_cor != "verde"
        if not info["recem_resolvido"]:
            return
        chamado = info.get("chamado_interno", "")
        if not re.match(r"^IS-\d+$", chamado):
            return
        try:
            jira_client.close_ticket(config.JIRA_URL, config.JIRA_EMAIL, config.JIRA_TOKEN, chamado, info["status"])
        except Exception as e:
            errors.append(f"Nao consegui fechar {chamado} no Jira automaticamente: {e}")

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
                    marcar_se_recem_resolvido(info, "selbetti", field(r, "numero_ticket"))
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
                        marcar_se_recem_resolvido(info, "simpress", field(r, "numero_ticket"))
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
