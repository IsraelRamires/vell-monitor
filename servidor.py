"""Servidor do painel: atualiza os dados a cada poucos minutos e mostra o painel
no navegador em http://localhost:8765 .  Para iniciar:  python servidor.py
"""
import json, os, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vellcfg as C
import coletor, metricas

STATE = {"json": b'{"vazio": true}', "status": "iniciando", "detalhe": "", "erro": "", "ok_em": 0}
LOCK = threading.Lock()


def recompute():
    data = metricas.build()
    addrs = data.pop("_enderecos_top", [])
    with LOCK:
        STATE["json"] = json.dumps(data, ensure_ascii=False, allow_nan=False, default=lambda o: None).encode("utf-8")
        STATE["ok_em"] = int(time.time())
    return addrs


def loop():
    first = True
    while True:
        try:
            if first and os.path.exists(C.DB_PATH):
                try:
                    recompute()          # mostra na hora o que já está salvo
                except Exception:
                    pass
            STATE["status"] = "coletando"

            def prog(i, t, tot):
                STATE["detalhe"] = f"Baixando histórico da blockchain: parte {i} de {t} ({tot} eventos)"
            coletor.update(prog)
            STATE["status"] = "calculando"
            addrs = recompute()
            con = coletor.db()
            try:
                before = con.execute("SELECT COUNT(*) FROM addr_info").fetchone()[0]
                coletor.check_contracts(con, addrs)
                after = con.execute("SELECT COUNT(*) FROM addr_info").fetchone()[0]
            finally:
                con.close()
            if after != before:
                recompute()
            STATE.update(status="ok", detalhe="", erro="")
        except Exception as e:
            STATE.update(status="erro", erro=repr(e)[:300])
            coletor.log("erro na atualização:", repr(e)[:300])
        first = False
        time.sleep(C.UPDATE_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(os.path.join(C.BASE_DIR, "painel.html"), "rb") as f:
                self._send(f.read(), "text/html; charset=utf-8")
        elif path == "/logo.jpg":
            try:
                with open(os.path.join(C.BASE_DIR, "logo.jpg"), "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                self._send(b"sem logo", "text/plain", 404)
        elif path == "/api/dados":
            with LOCK:
                body = STATE["json"]
            self._send(body, "application/json; charset=utf-8")
        elif path == "/api/status":
            s = {k: STATE[k] for k in ("status", "detalhe", "erro", "ok_em")}
            s["intervalo"] = C.UPDATE_SECONDS
            self._send(json.dumps(s, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        else:
            self._send(b"nao encontrado", "text/plain", 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    local = C.HOST in ("127.0.0.1", "localhost")
    url = f"http://localhost:{C.PORT}"
    srv = ThreadingHTTPServer((C.HOST, C.PORT), Handler)
    if local:
        coletor.log(f"Painel do VELL aberto em {url}  (feche esta janela para parar)")
    else:
        coletor.log(f"Painel do VELL no ar: escutando em {C.HOST}:{C.PORT}  (banco em {C.DB_PATH})")
    if local and not os.environ.get("VELL_SEM_NAVEGADOR"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
