import http.server
import json
import os
import sys
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8743

sys.path.insert(0, BASE_DIR)
import check_status  # noqa: E402

_lock = threading.Lock()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_GET(self):
        if self.path == "/":
            self.path = "/dashboard.html"
        super().do_GET()

    def _send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/atualizar":
            with _lock:
                try:
                    payload = check_status.build_payload()
                    check_status.write_data_js(payload)
                    self._send_json(200, payload)
                except Exception as e:
                    self._send_json(500, {"erro": str(e)})
            return

        if self.path == "/atualizar-ticket":
            with _lock:
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    req = json.loads(self.rfile.read(length) or b"{}")
                    info, payload = check_status.check_single_ticket(
                        req["fornecedor"],
                        req["numero_ticket"],
                        req.get("chamado_interno", ""),
                        req.get("motivo", ""),
                    )
                    self._send_json(200, {"ticket": info, "payload": payload})
                except Exception as e:
                    self._send_json(500, {"erro": str(e)})
            return

        if self.path == "/fechar-ticket":
            with _lock:
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    req = json.loads(self.rfile.read(length) or b"{}")
                    fechou = check_status.close_ticket_in_jira(req["chamado_interno"], req.get("status", ""))
                    payload = (
                        check_status.mark_ticket_fechado_no_jira(req["fornecedor"], req["numero_ticket"])
                        if fechou else check_status.load_data_payload()
                    )
                    self._send_json(200, {"fechado": fechou, "payload": payload})
                except Exception as e:
                    self._send_json(500, {"erro": str(e)})
            return

        self.send_error(404)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as httpd:
        httpd.serve_forever()
