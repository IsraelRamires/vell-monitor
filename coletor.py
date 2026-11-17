"""Coletor: baixa da blockchain (BSC) todos os eventos do token VELL e do par
VELL/WBNB e guarda num banco de dados local (SQLite). Só usa a biblioteca
padrão do Python. Rode sozinho para atualizar:  python coletor.py
"""
import json, os, sqlite3, time, urllib.request, urllib.error

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vellcfg as C

UA = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


# --------------------------------------------------------------------------- RPC
def _post(url, body, timeout=40):
    req = urllib.request.Request(url, json.dumps(body).encode(), UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def rpc(method, params, urls=None, tries=8):
    """Chama um método JSON-RPC, tentando cada servidor e repetindo em caso de falha."""
    urls = urls or [C.RPC_ARCHIVE] + C.RPC_RECENT
    errs = {}
    for attempt in range(tries):
        for u in urls:
            try:
                r = _post(u, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                if "result" in r:
                    return r["result"]
                errs[u] = str(r.get("error"))[:140]
            except urllib.error.HTTPError as e:
                errs[u] = f"HTTP {e.code} {e.read()[:100]!r}"
            except Exception as e:  # rede fora, tempo esgotado etc.
                errs[u] = repr(e)[:140]
        time.sleep(min(2.0 * (attempt + 1), 15))
    raise RuntimeError(f"RPC {method} falhou: " + " | ".join(f"{u.split('/')[2]}: {e}" for u, e in errs.items()))


def eth_call(to, data):
    return rpc("eth_call", [{"to": to, "data": data}, "latest"])


# --------------------------------------------------------------------------- Banco
def db():
    os.makedirs(os.path.dirname(C.DB_PATH), exist_ok=True)
    con = sqlite3.connect(C.DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS logs(
        block INTEGER, ts INTEGER, tx TEXT, li INTEGER, address TEXT,
        topic0 TEXT, t1 TEXT, t2 TEXT, t3 TEXT, data TEXT,
        PRIMARY KEY(block, li));
    CREATE INDEX IF NOT EXISTS logs_tx ON logs(tx);
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE IF NOT EXISTS bnb_price(ts INTEGER PRIMARY KEY, close REAL);
    CREATE TABLE IF NOT EXISTS token_price(sym TEXT, ts INTEGER, close REAL, PRIMARY KEY(sym, ts));
    CREATE TABLE IF NOT EXISTS addr_info(address TEXT PRIMARY KEY, is_contract INTEGER, checked INTEGER);
    """)
    return con


def meta_get(con, k, default=None):
    r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def meta_set(con, k, v):
    con.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


# --------------------------------------------------------------------------- Eventos
def _topic_addr(t):
    return "0x" + t[-40:] if t else None


def fetch_logs(con, progress=None):
    """Baixa os eventos novos desde o último bloco salvo."""
    head = int(rpc("eth_blockNumber", []), 16) - 3          # margem contra reorganização
    start = int(meta_get(con, "last_block", C.CREATION_BLOCK - 1)) + 1
    if start > head:
        return 0
    total, a = 0, start
    n_chunks = (head - start) // C.MAX_RANGE + 1
    i = 0
    while a <= head:
        b = min(a + C.MAX_RANGE - 1, head)
        flt = {"address": [C.TOKEN, C.PAIR], "fromBlock": hex(a), "toBlock": hex(b)}
        # consultas antigas precisam do servidor de arquivo; as recentes aceitam qualquer um
        old = a < head - 300_000
        res = rpc("eth_getLogs", [flt], urls=[C.RPC_ARCHIVE] if old else None)
        if old:
            time.sleep(0.2)   # não sobrecarrega o servidor gratuito
        rows = []
        for l in res:
            if l.get("removed"):
                continue
            t = l["topics"] + [None] * 4
            rows.append((int(l["blockNumber"], 16), int(l.get("blockTimestamp", "0x0"), 16),
                         l["transactionHash"], int(l["logIndex"], 16), l["address"].lower(),
                         t[0], _topic_addr(t[1]), _topic_addr(t[2]), _topic_addr(t[3]), l["data"]))
        # blocos sem horário (servidor antigo): busca o horário do bloco
        missing = sorted({r[0] for r in rows if not r[1]})
        if missing:
            tsmap = {}
            for j in range(0, len(missing), 50):
                part = missing[j:j + 50]
                out = _post(C.RPC_ARCHIVE, [{"jsonrpc": "2.0", "id": x, "method": "eth_getBlockByNumber",
                                             "params": [hex(x), False]} for x in part])
                for o in out:
                    tsmap[int(o["result"]["number"], 16)] = int(o["result"]["timestamp"], 16)
            rows = [(r[0], r[1] or tsmap[r[0]]) + r[2:] for r in rows]
        con.executemany("INSERT OR IGNORE INTO logs VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
        meta_set(con, "last_block", b)
        con.commit()
        total += len(rows)
        i += 1
        if progress and (i % 10 == 0 or b == head):
            progress(i, n_chunks, total)
        a = b + 1
    return total


# --------------------------------------------------------------------------- Preço do BNB
# data-api.binance.vision é o espelho público de dados da Binance: funciona também de servidores
# nos EUA (como os do GitHub), onde api.binance.com responde "451 - bloqueado".
BINANCE_HOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]


def binance_klines(sym, interval, start, limit=1000):
    err = None
    for host in BINANCE_HOSTS:
        try:
            return _get_json(f"{host}/api/v3/klines?symbol={sym}USDT&interval={interval}"
                             f"&startTime={start * 1000}&limit={limit}")
        except Exception as e:
            err = e
    raise err


def fetch_bnb_prices(con):
    """Preço do BNB em dólar, de hora em hora (Binance), desde a criação do token."""
    last = con.execute("SELECT MAX(ts) FROM bnb_price").fetchone()[0]
    start = (last - 2 * 3600) if last else 1779840000   # 27/05/2026
    n = 0
    while True:
        k = binance_klines("BNB", "1h", start)
        if not k:
            break
        con.executemany("INSERT INTO bnb_price(ts,close) VALUES(?,?) ON CONFLICT(ts) DO UPDATE SET close=excluded.close",
                        [(x[0] // 1000, float(x[4])) for x in k])
        n += len(k)
        if len(k) < 1000:
            break
        start = k[-1][0] // 1000 + 3600
    con.commit()
    return n


BNB_MINUTOS_DIAS = 40     # guarda o preço do BNB minuto a minuto só dos últimos 40 dias


def fetch_bnb_minutes(con):
    """Preço do BNB minuto a minuto: converte o preço do VELL para dólar no minuto exato
    (as variações de 1h, 24h, 7 e 30 dias ficam iguais às do DexScreener)."""
    con.execute("CREATE TABLE IF NOT EXISTS bnb_price_1m(ts INTEGER PRIMARY KEY, close REAL)")
    agora = int(time.time())
    limite = agora - BNB_MINUTOS_DIAS * 86400
    last = con.execute("SELECT MAX(ts) FROM bnb_price_1m").fetchone()[0]
    start = max(limite, (last - 120) if last else limite)
    n = 0
    while start < agora:
        k = binance_klines("BNB", "1m", start)
        if not k:
            break
        con.executemany("INSERT INTO bnb_price_1m(ts,close) VALUES(?,?) ON CONFLICT(ts) DO UPDATE SET close=excluded.close",
                        [(x[0] // 1000, float(x[4])) for x in k])
        n += len(k)
        if len(k) < 1000:
            break
        start = k[-1][0] // 1000 + 60
    con.execute("DELETE FROM bnb_price_1m WHERE ts < ?", (limite,))
    con.commit()
    return n


# --------------------------------------------------------------------------- Preço dos outros ativos
BINANCE_SYMS = ["BTC", "ETH", "SOL", "XRP", "TRX", "ZEC", "HYPE"]
CMC20_ID = 38442


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_token_prices(con):
    """Preço em dólar, de hora em hora, dos ativos usados na comparação (desde o lançamento do VELL)."""
    first = C.LAUNCH_TS - 86400
    for sym in BINANCE_SYMS:
        try:
            last = con.execute("SELECT MAX(ts) FROM token_price WHERE sym=?", (sym,)).fetchone()[0]
            start = (last - 2 * 3600) if last else first
            while True:
                k = binance_klines(sym, "1h", start)
                if not k:
                    break
                con.executemany("INSERT INTO token_price VALUES(?,?,?) ON CONFLICT(sym,ts) DO UPDATE SET close=excluded.close",
                                [(sym, x[0] // 1000, float(x[4])) for x in k])
                if len(k) < 1000:
                    break
                start = k[-1][0] // 1000 + 3600
        except Exception as e:
            log(f"aviso: preço de {sym} não atualizou:", repr(e)[:100])
    # CMC20 (índice do CoinMarketCap): a consulta devolve no máximo ~400 horas terminando em timeEnd
    try:
        import calendar
        last = con.execute("SELECT MAX(ts) FROM token_price WHERE sym='CMC20'").fetchone()[0]
        stop = (last - 2 * 3600) if last else first
        end = int(time.time())
        for _ in range(12):
            d = _get_json("https://api.coinmarketcap.com/data-api/v3.1/cryptocurrency/historical"
                          f"?id={CMC20_ID}&convertId=2781&interval=1h&timeStart={max(stop, end - 390 * 3600)}&timeEnd={end}")
            q = d.get("data", {}).get("quotes", [])
            rows = []
            for r in q:
                t = calendar.timegm(time.strptime(r["timeOpen"][:19], "%Y-%m-%dT%H:%M:%S"))
                rows.append(("CMC20", t, float(r["quote"]["close"])))
            con.executemany("INSERT INTO token_price VALUES(?,?,?) ON CONFLICT(sym,ts) DO UPDATE SET close=excluded.close", rows)
            if not rows or min(r[1] for r in rows) <= stop:
                break
            end = min(r[1] for r in rows) - 1
            time.sleep(0.5)
    except Exception as e:
        log("aviso: preço do CMC20 não atualizou:", repr(e)[:100])
    con.commit()


# --------------------------------------------------------------------------- Contrato ou carteira?
def check_contracts(con, addresses):
    """Descobre se cada endereço é um contrato (robô, pool, cofre) ou carteira comum."""
    known = {r[0] for r in con.execute("SELECT address FROM addr_info")}
    todo = [a for a in addresses if a not in known][:400]
    for j in range(0, len(todo), 40):
        part = todo[j:j + 40]
        try:
            out = _post(C.RPC_ARCHIVE, [{"jsonrpc": "2.0", "id": i, "method": "eth_getCode",
                                         "params": [a, "latest"]} for i, a in enumerate(part)])
            for o in out:
                code = o.get("result") or "0x"
                con.execute("INSERT OR REPLACE INTO addr_info VALUES(?,?,?)",
                            (part[o["id"]], 1 if len(code) > 2 else 0, int(time.time())))
        except Exception as e:
            log("aviso: não consegui verificar contratos:", repr(e)[:100])
            break
    con.commit()


def read_contract_state(con):
    """Lê dados atuais do contrato: dono, fornecimento total e total de cotas de liquidez."""
    out = {}
    try:
        out["owner"] = "0x" + eth_call(C.TOKEN, "0x8da5cb5b")[-40:]
    except Exception:
        out["owner"] = None
    try:
        out["total_supply"] = int(eth_call(C.TOKEN, "0x18160ddd"), 16) / 10 ** C.DECIMALS
        out["lp_supply"] = int(eth_call(C.PAIR, "0x18160ddd"), 16) / 1e18
    except Exception as e:
        log("aviso: leitura do contrato falhou:", repr(e)[:100])
    for k, v in out.items():
        meta_set(con, "state_" + k, v)
    con.commit()
    return out


def update(progress=None):
    con = db()
    try:
        n = fetch_logs(con, progress)
        try:
            fetch_bnb_prices(con)
        except Exception as e:
            log("aviso: preço do BNB não atualizou:", repr(e)[:100])
        try:
            fetch_bnb_minutes(con)
        except Exception as e:
            log("aviso: preço do BNB minuto a minuto não atualizou:", repr(e)[:100])
        fetch_token_prices(con)
        read_contract_state(con)
        meta_set(con, "last_update", int(time.time()))
        con.commit()
        return n
    finally:
        con.close()


if __name__ == "__main__":
    log("Atualizando dados do VELL... (a primeira vez leva de 10 a 20 minutos)")
    n = update(lambda i, t, tot: log(f"  parte {i}/{t} — {tot} eventos novos"))
    log(f"Pronto: {n} eventos novos salvos em {C.DB_PATH}")
