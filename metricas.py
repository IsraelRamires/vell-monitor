"""Métricas: lê o banco local e calcula tudo o que o painel mostra.
Rode sozinho para ver um resumo no terminal:  python metricas.py
"""
import bisect, datetime as dt, json, math, sqlite3, time
from collections import defaultdict, deque

import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vellcfg as C

T_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
T_SWAP = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
T_SYNC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"
T_MINT = "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f"
T_BURN = "0xdccd412f0b1252819cb1fd330b93224ca42612892bb3f4f789976e6d81936496"
T_OWNER = "0x8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e0"

ZERO = "0x0000000000000000000000000000000000000000"
DEAD = "0x000000000000000000000000000000000000dead"
KNOWN = {
    ZERO: "Endereço zero (queima)",
    DEAD: "Endereço morto (queima)",
    "0x10ed43c718714eb63d5aa57b78b54704e256024e": "Roteador PancakeSwap",
    "0x13f4ea83d0bd40e75c8222255bc855a974568dd4": "Roteador PancakeSwap v3",
    "0x407993575c91ce7643a4d4ccacc9a98c36ee1bbe": "Cofre PinkLock (travado)",
    "0xc765bddb93b0d1c1a88282ba0fa6b2d00e3e0c83": "Cofre Unicrypt (travado)",
    "0xae7e6cabad8d80f0b4e1c4dde2a5db7201ef1252": "Cofre Mudra (travado)",
}
BURN_ADDRS = {ZERO, DEAD}
TZ = C.TZ_OFFSET_HOURS * 3600                       # fuso para mostrar datas e horas (Brasília)
DTZ = -int(getattr(C, "FECHAMENTO_DIA_UTC", 0)) * 3600  # dias fecham às 00:00 UTC = 21:00 de Brasília
DAY = 86400
DUST = 1e-6


def words(data):
    h = data[2:]
    return [int(h[i:i + 64], 16) for i in range(0, len(h), 64)]


def local_day(ts):
    """Número do dia; cada dia vai das 21:00 às 21:00 de Brasília (00:00 a 00:00 UTC)."""
    return (ts + DTZ) // DAY


def day_str(d):
    return (dt.datetime(1970, 1, 1) + dt.timedelta(days=d)).strftime("%Y-%m-%d")


def br(n, sign=False):
    """Número no formato brasileiro (ponto como separador de milhar)."""
    return f"{n:{'+' if sign else ''},.0f}".replace(",", ".")


def pct(a, b):
    return (a / b - 1) * 100 if b else None


def corr_beta(x, y):
    n = len(x)
    if n < 6:
        return None, None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    if sxx <= 0 or syy <= 0:
        return None, None
    return sxy / math.sqrt(sxx * syy), sxy / syy  # correlação, beta de x em relação a y


_LEITURA_CACHE = {}   # placares de horas passadas, guardados entre uma atualização e outra


def build():
    t_start = time.time()
    con = sqlite3.connect(C.DB_PATH, timeout=30)
    meta = dict(con.execute("SELECT k, v FROM meta").fetchall())
    rows = con.execute("SELECT block, ts, tx, li, address, topic0, t1, t2, data FROM logs ORDER BY block, li").fetchall()
    bnb_rows = con.execute("SELECT ts, close FROM bnb_price ORDER BY ts").fetchall()
    try:
        bnb_min = con.execute("SELECT ts, close FROM bnb_price_1m ORDER BY ts").fetchall()
    except sqlite3.OperationalError:
        bnb_min = []
    if bnb_min:      # minuto a minuto onde existe (últimos 40 dias); de hora em hora antes disso
        bnb_rows = [r for r in bnb_rows if r[0] + 3600 <= bnb_min[0][0]] + bnb_min
    contracts = dict(con.execute("SELECT address, is_contract FROM addr_info").fetchall())
    try:
        tok_rows = con.execute("SELECT sym, ts, close FROM token_price ORDER BY sym, ts").fetchall()
    except sqlite3.OperationalError:
        tok_rows = []
    con.close()
    now = int(time.time())
    if not rows:
        return {"vazio": True, "gerado_em": now}

    bnb_ts = [r[0] for r in bnb_rows]
    bnb_px = [r[1] for r in bnb_rows]

    def bnb_usd(ts):
        if not bnb_ts:
            return 0.0
        i = bisect.bisect_right(bnb_ts, ts) - 1
        return bnb_px[max(i, 0)]

    total_supply = float(meta.get("state_total_supply") or 0) or 500_000_000.0
    owner = (meta.get("state_owner") or "").lower() or None
    D = 10 ** C.DECIMALS

    # ------------------------------------------------------------ separa eventos por transação
    txs = {}        # tx -> {"ts","block","tr":[(from,to,val)],"sw":[...],...}
    order = []
    syncs = []      # (ts, r0, r1)
    lp_bal = defaultdict(float)
    liq_events = []
    owner_changes = []
    deployer = None
    other_events = defaultdict(int)
    for block, ts, tx, li, addr, t0, t1, t2, data in rows:
        e = txs.get(tx)
        if e is None:
            e = txs[tx] = {"ts": ts, "block": block, "tr": [], "sw": [], "mint": [], "burn": [], "lp": []}
            order.append(tx)
        if addr == C.TOKEN:
            if t0 == T_TRANSFER:
                vw = int(data, 16) if len(data) > 2 else 0
                e["tr"].append((t1, t2, vw / D, vw))
                if deployer is None and t1 == ZERO:
                    deployer = t2
            elif t0 == T_OWNER:
                owner_changes.append({"ts": ts, "de": t1, "para": t2, "tx": tx})
            elif t0 != "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925":  # ignora Approval
                other_events[t0] += 1
        else:  # par
            if t0 == T_SWAP:
                w = words(data)
                e["sw"].append((w[0] / D, w[1] / 1e18, w[2] / D, w[3] / 1e18, t1, t2))
            elif t0 == T_SYNC:
                w = words(data)
                syncs.append((ts, w[0] / D, w[1] / 1e18))
                e["sync"] = (w[0] / D, w[1] / 1e18)
            elif t0 == T_MINT:
                w = words(data)
                e["mint"].append((w[0] / D, w[1] / 1e18, t1))
            elif t0 == T_BURN:
                w = words(data)
                e["burn"].append((w[0] / D, w[1] / 1e18, t2))
            elif t0 == T_TRANSFER:
                v = int(data, 16) / 1e18 if len(data) > 2 else 0.0
                e["lp"].append((t1, t2, v))
                lp_bal[t1] -= v
                lp_bal[t2] += v

    special = {C.PAIR, C.TOKEN, ZERO, DEAD}

    # ------------------------------------------------------------ repassa a história, transação por transação
    bal = defaultdict(float)
    W = {}  # estatísticas por carteira

    def wallet(a):
        w = W.get(a)
        if w is None:
            w = W[a] = {"first": None, "last": None, "buy_tok": 0.0, "buy_usd": 0.0, "buy_bnb": 0.0, "n_buy": 0,
                        "sell_tok": 0.0, "sell_usd": 0.0, "sell_bnb": 0.0, "n_sell": 0,
                        "in_tok": 0.0, "out_tok": 0.0, "cost": 0.0, "qty": 0.0, "realized": 0.0,
                        "from_owner": 0.0, "real_lot": 0.0, "custo_vendido": 0.0, "venda_sem_custo": 0.0}
        return w

    trades = []
    deltas_log = []          # (ts, addr, delta) para variação de saldo por período
    edges = defaultdict(set)  # ligações diretas entre carteiras (transferências fora do pool)
    holders_n = 0
    bal_w = defaultdict(int)  # saldos exatos (unidades inteiras do contrato)
    hc = []                  # (quando, número de holders) a cada mudança
    hio = []                 # (quando, +1 carteira passou a ter VELL / -1 carteira zerou)
    holders_daily = {}
    new_holders_daily = defaultdict(int)
    seen_holder = set()
    burned = 0.0
    cart_ev = defaultdict(list)   # histórico de cada carteira (consulta de lucro/prejuízo por período)
    burns = []               # (quando, quem queimou, VELL, transação, preço US$ no momento)
    dist_hubs = {a for a in (owner, deployer) if a}
    # --- Short-Term Holders: cada carteira guarda "lotes" [quando recebeu, quantidade, preço de custo]
    lots = defaultdict(deque)
    # limites de idade de um lote; "tudo" = recebido antes do lançamento e nunca movido desde então
    STH_THR = {"1d": DAY, "7d": 7 * DAY, "30d": 30 * DAY, "180d": 180 * DAY, "365d": 365 * DAY, "tudo": None}

    def lim_de(k, t):
        lim = STH_THR[k]
        return lim if lim is not None else t - C.LAUNCH_TS
    sth_serie = {k: [] for k in STH_THR}
    sth_venda = {k: defaultdict(lambda: [0.0, 0.0, 0.0]) for k in STH_THR}   # por dia: [valor vendido, custo, quantidade]
    # Long-Term Holders: os mesmos lotes, olhando os que têm MAIS idade que o limite
    lth_serie = {k: [] for k in STH_THR}
    lth_venda = {k: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]) for k in STH_THR}   # por dia: [valor c/ custo, custo, quantidade, valor total]
    # cada venda, com o horário exato, para somar janelas corridas (últimas 24h, últimos 7 dias):
    # (quando, valor c/ custo, custo, quantidade, valor total)
    sth_ev = {k: [] for k in STH_THR}
    lth_ev = {k: [] for k in STH_THR}

    def janela_ev(evs, ini, fim):
        """Soma as vendas entre 'ini' e 'fim': [valor c/ custo, custo, quantidade, valor total]."""
        s_ = [0.0, 0.0, 0.0, 0.0]
        for x in evs:
            if ini <= x[0] < fim:
                s_[0] += x[1]; s_[1] += x[2]; s_[2] += x[3]; s_[3] += x[4]
        return s_
    cur_px = None                      # preço de mercado em dólar no momento da transação
    snap_day = None
    launch_day = local_day(C.LAUNCH_TS)

    def sth_foto(ts_fim, px):
        """Soma, para cada limite de idade, os tokens recebidos há menos tempo que o limite."""
        res = {k: {"qtd": 0.0, "custo": 0.0, "qtd_custo": 0.0, "lucro": 0.0, "cart": 0} for k in STH_THR}
        resl = {k: {"qtd": 0.0, "custo": 0.0, "qtd_custo": 0.0, "lucro": 0.0, "cart": 0} for k in STH_THR}
        total = 0.0
        for a_, dq in lots.items():
            tem = {k: False for k in STH_THR}
            teml = {k: False for k in STH_THR}
            for lt in dq:
                total += lt[1]
                idade = ts_fim - lt[0]
                for k in STH_THR:
                    novo_ = idade < lim_de(k, ts_fim)
                    r_ = res[k] if novo_ else resl[k]
                    r_["qtd"] += lt[1]
                    if lt[1] > DUST:
                        if novo_:
                            tem[k] = True
                        else:
                            teml[k] = True
                    if lt[2]:
                        r_["custo"] += lt[1] * lt[2]; r_["qtd_custo"] += lt[1]
                        if px and lt[2] <= px:
                            r_["lucro"] += lt[1]
            for k in STH_THR:
                if tem[k]:
                    res[k]["cart"] += 1
                if teml[k]:
                    resl[k]["cart"] += 1
        sth_foto.longo = resl
        return res, total

    def sth_guarda(dia, ts_fim, px):
        res, total = sth_foto(ts_fim, px)
        for k, r_ in res.items():
            v = sth_venda[k].get(dia)
            sth_serie[k].append({"dia": day_str(dia), "qtd": r_["qtd"], "pct": r_["qtd"] / total * 100 if total else 0,
                                 "custo": r_["custo"] / r_["qtd_custo"] if r_["qtd_custo"] else None, "preco": px,
                                 "sopr": v[0] / v[1] if v and v[1] > 0 else None, "vendido": v[2] if v else 0.0})
        for k, r_ in sth_foto.longo.items():
            v = lth_venda[k].get(dia)
            lth_serie[k].append({"dia": day_str(dia), "qtd": r_["qtd"], "pct": r_["qtd"] / total * 100 if total else 0,
                                 "custo": r_["custo"] / r_["qtd_custo"] if r_["qtd_custo"] else None, "preco": px,
                                 "sopr": v[0] / v[1] if v and v[1] > 0 else None, "vendido": v[2] if v else 0.0,
                                 "vendido_usd": v[3] if v else 0.0})
        return res, total

    for tx in order:
        e = txs[tx]
        ts = e["ts"]
        d_now_ = local_day(ts)
        if snap_day is None:
            snap_day = d_now_
        while snap_day < d_now_:               # fecha os dias que terminaram
            if snap_day >= launch_day and cur_px:
                sth_guarda(snap_day, (snap_day + 1) * DAY - DTZ, cur_px)
            snap_day += 1
        delta = defaultdict(float)
        wdelta = defaultdict(int)          # o mesmo em unidades inteiras do contrato (para contar holders sem erro de arredondamento)
        for f, t, v, vw in e["tr"]:
            delta[f] -= v
            delta[t] += v
            wdelta[f] -= vw
            wdelta[t] += vw
            if t in BURN_ADDRS and f != ZERO and v > 0:      # queima: VELL enviado para endereço morto/zero
                burns.append((ts, f, v, tx, cur_px))
            if v > 0 and f in dist_hubs and t not in special and t not in dist_hubs:
                wallet(t)["from_owner"] += v
            if v > 0 and t in dist_hubs and f not in special and f not in dist_hubs:
                wallet(f)["from_owner"] -= v
            if f not in special and t not in special and f not in KNOWN and t not in KNOWN and v > 0:
                edges[f].add(t)
                edges[t].add(f)
        trade = None
        if e["sw"]:
            tok_in = sum(s[0] for s in e["sw"]); bnb_in = sum(s[1] for s in e["sw"])
            tok_out = sum(s[2] for s in e["sw"]); bnb_out = sum(s[3] for s in e["sw"])
            cand = {a: d for a, d in delta.items() if a not in (C.PAIR, ZERO, DEAD)}
            px = bnb_usd(ts)
            if tok_out > tok_in and bnb_in > 0:        # compra
                tok, bnb = tok_out - tok_in, bnb_in - bnb_out
                who = max(cand, key=cand.get) if cand else None
                got = cand.get(who, 0.0) if who else 0.0
                tax = max(0.0, 1 - got / tok) if tok and got > 0 else None
                trade = {"lado": "compra", "tok": tok, "bnb": bnb, "who": who, "real": got, "tax": tax}
            elif tok_in > tok_out and bnb_out > 0:     # venda
                tok, bnb = tok_in - tok_out, bnb_out - bnb_in
                who = min(cand, key=cand.get) if cand else None
                sent = -cand.get(who, 0.0) if who else 0.0
                tax = max(0.0, 1 - tok / sent) if sent > 0 and who != C.TOKEN else None
                trade = {"lado": "venda", "tok": tok, "bnb": bnb, "who": who, "real": sent, "tax": tax}
            if trade and trade["bnb"] > 0 and trade["tok"] > 0:
                trade.update(ts=ts, tx=tx, usd=trade["bnb"] * px, preco_bnb=trade["bnb"] / trade["tok"],
                             preco_usd=trade["bnb"] * px / trade["tok"])
                trades.append(trade)
            else:
                trade = None
        # holders contados como na BscScan: todo endereço com saldo maior que zero
        # (inclui pool, contrato, endereço de queima e carteiras com quantias mínimas)
        for a, dw in wdelta.items():
            if not dw:
                continue
            bw0 = bal_w[a]; bw1 = bw0 + dw; bal_w[a] = bw1
            if bw0 <= 0 < bw1:
                holders_n += 1
                hio.append((ts, 1))
                if a not in seen_holder:
                    seen_holder.add(a)
                    new_holders_daily[local_day(ts)] += 1
            elif bw1 <= 0 < bw0:
                holders_n -= 1
                hio.append((ts, -1))
        for a, d in delta.items():
            if abs(d) < 1e-12:
                continue
            before = bal[a]
            after = before + d
            bal[a] = after
            if a in BURN_ADDRS:
                if a == DEAD or (a == ZERO and d > 0):
                    burned += max(d, 0)
                continue
            if a in special:
                continue
            if a in KNOWN:
                w = wallet(a)
                w["first"] = w["first"] or ts
                w["last"] = ts
                continue
            deltas_log.append((ts, a, d))
            w = wallet(a)
            if w["first"] is None:
                w["first"] = ts
            w["last"] = ts
            is_trader = trade is not None and trade["who"] == a
            # histórico da carteira para a consulta por período: [quando, VELL (+/-), 1=compra 2=venda 0=transferência, US$]
            if is_trader and trade["lado"] == "compra" and d > 0:
                cart_ev[a].append([ts, round(d, 6), 1, round(trade["usd"], 4)])
            elif is_trader and trade["lado"] == "venda" and d < 0:
                cart_ev[a].append([ts, round(d, 6), 2, round(trade["usd"], 4)])
            else:
                cart_ev[a].append([ts, round(d, 6), 0, round(abs(d) * (cur_px or 0), 4)])
            if a not in dist_hubs:
                if d > 0:
                    custo_ = trade["usd"] / d if (is_trader and trade["lado"] == "compra") else cur_px
                    lots[a].append([ts, d, custo_])
                else:
                    falta, dq_ = -d, lots[a]
                    venda_ = is_trader and trade["lado"] == "venda"
                    # só conta como venda a parte que foi para o pool (até 25% de taxa); o resto da saída é transferência
                    resta_v = min(-d, trade["tok"] / 0.75) if venda_ else 0.0
                    pv_ = trade["usd"] / resta_v if venda_ and resta_v > 0 else None
                    while falta > 1e-12 and dq_:
                        lt = dq_[0]
                        usa = min(falta, lt[1])
                        uv = min(usa, resta_v)
                        if uv > 0 and pv_:
                            if lt[2]:      # resultado da venda, lote a lote (preço de venda - custo do lote)
                                w["real_lot"] += uv * (pv_ - lt[2]); w["custo_vendido"] += uv * lt[2]
                            else:
                                w["venda_sem_custo"] += uv * pv_
                            idade = ts - lt[0]
                            for k_ in STH_THR:
                                if idade < lim_de(k_, ts):
                                    if lt[2]:
                                        acc_ = sth_venda[k_][d_now_]
                                        acc_[0] += uv * pv_; acc_[1] += uv * lt[2]; acc_[2] += uv
                                        sth_ev[k_].append((ts, uv * pv_, uv * lt[2], uv, uv * pv_))
                                else:
                                    acc_ = lth_venda[k_][d_now_]
                                    acc_[2] += uv; acc_[3] += uv * pv_
                                    if lt[2]:
                                        acc_[0] += uv * pv_; acc_[1] += uv * lt[2]
                                    lth_ev[k_].append((ts, uv * pv_ if lt[2] else 0.0, uv * lt[2] if lt[2] else 0.0, uv, uv * pv_))
                        resta_v -= uv
                        lt[1] -= usa; falta -= usa
                        if lt[1] <= 1e-12:
                            dq_.popleft()
            if is_trader and trade["lado"] == "compra" and d > 0:
                w["buy_tok"] += d; w["buy_usd"] += trade["usd"]; w["buy_bnb"] += trade["bnb"]; w["n_buy"] += 1
                w["qty"] += d; w["cost"] += trade["usd"]
            elif is_trader and trade["lado"] == "venda" and d < 0:
                sold = -d
                w["sell_tok"] += sold; w["sell_usd"] += trade["usd"]; w["sell_bnb"] += trade["bnb"]; w["n_sell"] += 1
                avg = w["cost"] / w["qty"] if w["qty"] > 0 else 0.0
                part = min(sold, w["qty"])
                w["realized"] += trade["usd"] - avg * part
                w["cost"] -= avg * part; w["qty"] = max(0.0, w["qty"] - sold)
            elif d > 0:
                w["in_tok"] += d; w["qty"] += d
            else:
                out = -d
                w["out_tok"] += out
                avg = w["cost"] / w["qty"] if w["qty"] > 0 else 0.0
                part = min(out, w["qty"])
                w["cost"] -= avg * part; w["qty"] = max(0.0, w["qty"] - out)
        if e.get("sync") and e["sync"][0] > 0:
            cur_px = e["sync"][1] / e["sync"][0] * bnb_usd(ts)
        holders_daily[local_day(ts)] = holders_n
        if not hc or hc[-1][1] != holders_n:
            hc.append((ts, holders_n))
        px_now = bnb_usd(ts)
        for a0, a1, who in e["mint"]:
            prov = next((t for f, t, v in e["lp"] if f == ZERO and t != ZERO), who)
            if 2 * a1 * px_now >= 1:
                liq_events.append({"ts": ts, "tipo": "entrada", "tok": a0, "bnb": a1, "usd": 2 * a1 * px_now, "quem": prov, "tx": tx})
        for a0, a1, to in e["burn"]:
            prov = next((f for f, t, v in e["lp"] if t == C.PAIR and f != ZERO), to)
            if 2 * a1 * px_now >= 1:
                liq_events.append({"ts": ts, "tipo": "saida", "tok": a0, "bnb": a1, "usd": 2 * a1 * px_now, "quem": prov, "tx": tx})

    hoje_ = local_day(now)
    while snap_day is not None and snap_day < hoje_:
        if snap_day >= launch_day and cur_px:
            sth_guarda(snap_day, (snap_day + 1) * DAY - DTZ, cur_px)
        snap_day += 1
    sth, lth = {}, {}
    if cur_px:
        res_now, total_now = sth_guarda(hoje_, now, cur_px)
        for k, r_ in res_now.items():
            custo_med = r_["custo"] / r_["qtd_custo"] if r_["qtd_custo"] else None
            v7, c7 = janela_ev(sth_ev[k], now - 7 * DAY, now + 1)[:2]   # últimos 7 dias corridos (7 x 24h)
            sth[k] ={"agora": {"qtd": r_["qtd"], "pct": r_["qtd"] / total_now * 100 if total_now else 0, "total": total_now,
                                "longo": total_now - r_["qtd"], "carteiras": r_["cart"], "custo": custo_med,
                                "mvrv": cur_px / custo_med if custo_med else None,
                                "pct_lucro": r_["lucro"] / r_["qtd_custo"] * 100 if r_["qtd_custo"] else None,
                                "resultado_usd": r_["qtd_custo"] * cur_px - r_["custo"] if r_["qtd_custo"] else None,
                                "valor_usd": r_["qtd"] * cur_px, "sopr7": v7 / c7 if c7 > 0 else None, "preco": cur_px},
                      "serie": sth_serie[k]}
        lth = {}
        for k, r_ in sth_foto.longo.items():
            custo_med = r_["custo"] / r_["qtd_custo"] if r_["qtd_custo"] else None
            j7 = janela_ev(lth_ev[k], now - 7 * DAY, now + 1)   # últimos 7 dias corridos (7 x 24h)
            v7, c7 = j7[0], j7[1]
            ser = lth_serie[k]
            ant = next((x for x in reversed(ser[:-7]) ), None) if len(ser) > 7 else None
            lth[k] = {"agora": {"qtd": r_["qtd"], "pct": r_["qtd"] / total_now * 100 if total_now else 0, "total": total_now,
                                "carteiras": r_["cart"], "custo": custo_med, "qtd_custo": r_["qtd_custo"],
                                "sem_custo": r_["qtd"] - r_["qtd_custo"],
                                "mvrv": cur_px / custo_med if custo_med else None,
                                "pct_lucro": r_["lucro"] / r_["qtd_custo"] * 100 if r_["qtd_custo"] else None,
                                "resultado_usd": r_["qtd_custo"] * cur_px - r_["custo"] if r_["qtd_custo"] else None,
                                "valor_usd": r_["qtd"] * cur_px, "sopr7": v7 / c7 if c7 > 0 else None,
                                "vendido7": j7[2], "vendido7_usd": j7[3],
                                "vendido24_usd": janela_ev(lth_ev[k], now - DAY, now + 1)[3],
                                "media_dia_ant_usd": janela_ev(lth_ev[k], now - 8 * DAY, now - DAY)[3] / 7,
                                "var7": r_["qtd"] - ant["qtd"] if ant else None, "preco": cur_px},
                      "serie": ser}

    # ------------------------------------------------------------ preço e liquidez de hora em hora
    launch = min((t["ts"] for t in trades), default=C.LAUNCH_TS)
    hours = []  # [ts_hora, preço_bnb, preço_usd, bnb_usd, liquidez_usd, reserva_tok, reserva_bnb]
    if syncs:
        h0 = (max(launch, syncs[0][0]) // 3600) * 3600
        i, last = 0, None
        for h in range(h0, now + 1, 3600):
            op = last[2] / last[1] if last and last[1] > 0 else None     # abertura = último preço antes da hora
            hi_ = lo_ = op
            while i < len(syncs) and syncs[i][0] < h + 3600:
                last = syncs[i]; i += 1
                if last[1] > 0:
                    p_ = last[2] / last[1]
                    if op is None:
                        op = hi_ = lo_ = p_
                    hi_ = max(hi_, p_); lo_ = min(lo_, p_)
            if last and last[1] > 0:
                b = bnb_usd(h + 3599)
                cl = last[2] / last[1]
                hours.append([h, cl, cl * b, b, 2 * last[2] * b, last[1], last[2], op * b, hi_ * b, lo_ * b])
    r_tok, r_bnb = (syncs[-1][1], syncs[-1][2]) if syncs else (0, 0)
    bnb_now = bnb_px[-1] if bnb_px else 0     # último preço do BNB (minuto atual)
    price_bnb = r_bnb / r_tok if r_tok else 0
    price = price_bnb * bnb_now

    sync_ts = [s[0] for s in syncs]

    def price_at(ts_back):
        """Preço (US$) no momento exato 'agora - ts_back': preço do pool naquele instante,
        convertido pelo preço do BNB naquele minuto. É o mesmo cálculo do DexScreener."""
        t = now - ts_back
        k = bisect.bisect_right(sync_ts, t) - 1
        if k < 0:
            return None
        s = syncs[k]
        return s[2] / s[1] * bnb_usd(t) if s[1] else None

    # ------------------------------------------------------------ rótulos e tipos
    def label(a):
        if a == C.PAIR:
            return "Pool de liquidez (PancakeSwap)"
        if a == C.TOKEN:
            return "Contrato do VELL"
        if a in KNOWN:
            return KNOWN[a]
        if a == owner:
            return "Dono do contrato"
        if a == deployer:
            return "Criador do contrato"
        return ""

    def kind(a):
        if a in special or a in KNOWN:
            return "especial"
        c = contracts.get(a)
        return "contrato" if c == 1 else ("carteira" if c == 0 else "?")

    def tier(b):
        p = b / total_supply * 100
        return "baleia" if p >= C.WHALE_PCT else "tubarão" if p >= C.SHARK_PCT else "peixe" if p >= 0.01 else "camarão"

    # variação de saldo por janela
    def window_delta(sec):
        cut = now - sec
        out = defaultdict(float)
        for ts, a, d in reversed(deltas_log):
            if ts < cut:
                break
            out[a] += d
        return out
    d24, d7, d30 = window_delta(DAY), window_delta(7 * DAY), window_delta(30 * DAY)
    # início do mês e do ano atuais (no fuso do painel), em segundos atrás
    _ld = dt.datetime.utcfromtimestamp(now + DTZ)
    sec_mes = now - (int((dt.datetime(_ld.year, _ld.month, 1) - dt.datetime(1970, 1, 1)).total_seconds()) - DTZ)
    sec_ano = now - (int((dt.datetime(_ld.year, 1, 1) - dt.datetime(1970, 1, 1)).total_seconds()) - DTZ)
    dmes, dano, dtudo = window_delta(sec_mes), window_delta(sec_ano), window_delta(now)

    circulating = total_supply - sum(max(bal[a], 0) for a in BURN_ADDRS)
    holders = sorted(((a, b) for a, b in bal.items() if b > DUST and a not in BURN_ADDRS), key=lambda x: -x[1])

    def wallet_row(a, b):
        w = W.get(a) or wallet(a)
        avg_buy = w["buy_usd"] / w["buy_tok"] if w["buy_tok"] else None
        avg_sell = w["sell_usd"] / w["sell_tok"] if w["sell_tok"] else None
        avg_cost = w["cost"] / w["qty"] if w["qty"] > DUST and w["cost"] > 0 else None
        unreal = b * price - w["cost"] if w["buy_tok"] else None
        origem = ("comprou no pool" if w["buy_tok"] and not w["in_tok"] else
                  "recebeu por transferência" if w["in_tok"] and not w["buy_tok"] else
                  "comprou e recebeu" if w["buy_tok"] else "—")
        return {"end": a, "rotulo": label(a), "tipo": kind(a), "faixa": tier(b), "saldo": b,
                "pct": b / total_supply * 100, "usd": b * price,
                "d24": d24.get(a, 0.0), "d7": d7.get(a, 0.0), "d30": d30.get(a, 0.0),
                "comprou": w["buy_tok"], "comprou_usd": w["buy_usd"], "vendeu": w["sell_tok"], "vendeu_usd": w["sell_usd"],
                "recebeu": w["in_tok"], "enviou": w["out_tok"], "n_compras": w["n_buy"], "n_vendas": w["n_sell"],
                "preco_medio_compra": avg_buy, "preco_medio_venda": avg_sell, "custo_medio": avg_cost,
                "lucro_realizado": w["realized"] if w["n_sell"] else None, "lucro_aberto": unreal,
                "primeira": w["first"], "ultima": w["last"], "origem": origem, "do_dono": w["from_owner"]}

    top = [wallet_row(a, b) for a, b in holders[:150]]
    non_pool = [(a, b) for a, b in holders if a not in (C.PAIR, C.TOKEN)]

    def share(n):
        return sum(b for _, b in non_pool[:n]) / total_supply * 100
    tiers = defaultdict(lambda: [0, 0.0])
    for a, b in non_pool:
        t = tiers[tier(b)]
        t[0] += 1; t[1] += b

    # acumuladores e distribuidores
    def movers(dm, n=15):
        items = [(a, d) for a, d in dm.items() if a not in special and abs(d) > DUST]
        up = sorted(items, key=lambda x: -x[1])[:n]
        down = sorted(items, key=lambda x: x[1])[:n]
        f = lambda a, d: {"end": a, "rotulo": label(a), "delta": d, "delta_usd": d * price, "saldo": bal.get(a, 0.0),
                          "pct": bal.get(a, 0.0) / total_supply * 100}
        return {"acumulou": [f(a, d) for a, d in up if d > 0], "distribuiu": [f(a, d) for a, d in down if d < 0]}

    # lucro: quem mais ganhou / perdeu
    pnl = []
    for a, w in W.items():
        if a in special or not (w["n_buy"] or w["n_sell"]):
            continue
        b = max(bal.get(a, 0.0), 0.0)
        unreal = b * price - w["cost"] if w["buy_tok"] else 0.0
        pnl.append({"end": a, "rotulo": label(a), "realizado": w["realized"], "aberto": unreal,
                    "total": w["realized"] + unreal, "comprou_usd": w["buy_usd"], "vendeu_usd": w["sell_usd"],
                    "saldo": b, "n": w["n_buy"] + w["n_sell"], "recebeu": w["in_tok"]})
    pnl.sort(key=lambda x: -x["total"])

    # consulta de carteira: todas as carteiras, compactas (vai num arquivo separado, api/carteiras)
    CAMPOS_CART = ["saldo", "comprou", "comprou_usd", "n_compras", "vendeu", "vendeu_usd", "n_vendas", "recebeu", "enviou",
                   "realizado", "custo_vendido", "venda_sem_custo", "custo_saldo", "qtd_com_custo", "qtd_sem_custo", "primeira", "ultima", "tipo", "rotulo"]
    carteiras_idx = {}
    for a, w in W.items():
        if a in special:
            continue
        b = max(bal.get(a, 0.0), 0.0)
        c_ = q_ = s_ = 0.0
        for lt in lots.get(a, ()):
            if lt[1] <= DUST:
                continue
            if lt[2]:
                c_ += lt[1] * lt[2]; q_ += lt[1]
            else:
                s_ += lt[1]
        r6 = lambda x: round(x, 6)
        carteiras_idx[a] = [r6(b), r6(w["buy_tok"]), r6(w["buy_usd"]), w["n_buy"], r6(w["sell_tok"]), r6(w["sell_usd"]), w["n_sell"],
                            r6(w["in_tok"]), r6(w["out_tok"]), r6(w["real_lot"]), r6(w["custo_vendido"]), r6(w["venda_sem_custo"]), r6(c_), r6(q_), r6(s_), w["first"], w["last"],
                            kind(a), label(a)]

    # grupos de carteiras ligadas por transferências diretas
    hubs = {a for a, s in edges.items() if len(s) > 15} | dist_hubs
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x]); x = parent[x]
        return x
    for a, s in edges.items():
        if a in hubs or contracts.get(a) == 1:
            continue
        for b_ in s:
            if b_ in hubs or contracts.get(b_) == 1:
                continue
            ra, rb = find(a), find(b_)
            if ra != rb:
                parent[ra] = rb
    groups = defaultdict(list)
    for a in edges:
        if a not in hubs and contracts.get(a) != 1:
            groups[find(a)].append(a)
    clusters = []
    for g in groups.values():
        if len(g) < 2:
            continue
        s = sum(max(bal.get(a, 0.0), 0.0) for a in g)
        clusters.append({"n": len(g), "saldo": s, "pct": s / total_supply * 100, "usd": s * price,
                         "comprou_usd": sum(W[a]["buy_usd"] for a in g if a in W),
                         "vendeu_usd": sum(W[a]["sell_usd"] for a in g if a in W),
                         "d7": sum(d7.get(a, 0.0) for a in g),
                         "membros": sorted(({"end": a, "saldo": max(bal.get(a, 0.0), 0.0)} for a in g), key=lambda x: -x["saldo"])[:12]})
    clusters.sort(key=lambda x: -x["saldo"])

    # distribuição inicial: quem recebeu direto do dono/criador
    insiders = []
    for a, w in W.items():
        if w["from_owner"] > 0 and a not in dist_hubs:
            b = max(bal.get(a, 0.0), 0.0)
            insiders.append({"end": a, "rotulo": label(a), "tipo": kind(a), "recebeu": w["from_owner"],
                             "pct_recebido": w["from_owner"] / total_supply * 100, "saldo": b,
                             "pct_saldo": b / total_supply * 100, "vendeu": w["sell_tok"], "vendeu_usd": w["sell_usd"],
                             "enviou": w["out_tok"], "ultima": w["last"], "d7": d7.get(a, 0.0)})
    insiders.sort(key=lambda x: -x["recebeu"])
    ins_recv = sum(x["recebeu"] for x in insiders)
    ins_bal = sum(x["saldo"] for x in insiders)

    # ------------------------------------------------------------ volume por período
    def agg():
        return {"compra_usd": 0.0, "venda_usd": 0.0, "bnb": 0.0, "n_compra": 0, "n_venda": 0,
                "compradores": set(), "vendedores": set(), "tok": 0.0}
    by_day = defaultdict(agg)
    heat = [[0.0] * 24 for _ in range(7)]
    for t in trades:
        d = by_day[local_day(t["ts"])]
        k = "compra" if t["lado"] == "compra" else "venda"
        d[k + "_usd"] += t["usd"]; d["bnb"] += t["bnb"]; d["tok"] += t["tok"]; d["n_" + k] += 1
        d["compradores" if k == "compra" else "vendedores"].add(t["who"])
        lt = dt.datetime.utcfromtimestamp(t["ts"] + TZ)
        heat[lt.weekday()][lt.hour] += t["usd"]

    def finish(key, a):
        tot = a["compra_usd"] + a["venda_usd"]
        n = a["n_compra"] + a["n_venda"]
        return {"periodo": key, "volume_usd": tot, "compra_usd": a["compra_usd"], "venda_usd": a["venda_usd"],
                "liquido_usd": a["compra_usd"] - a["venda_usd"], "bnb": a["bnb"], "tokens": a["tok"],
                "n": n, "n_compra": a["n_compra"], "n_venda": a["n_venda"],
                "compradores": len(a["compradores"]), "vendedores": len(a["vendedores"]),
                "ticket_medio": tot / n if n else 0}

    def merge(dst, src):
        for k in ("compra_usd", "venda_usd", "bnb", "tok", "n_compra", "n_venda"):
            dst[k] += src[k]
        dst["compradores"] |= src["compradores"]; dst["vendedores"] |= src["vendedores"]

    days_sorted = sorted(by_day)
    daily, weekly, monthly, yearly = [], defaultdict(agg), defaultdict(agg), defaultdict(agg)
    if days_sorted:
        for d in range(days_sorted[0], local_day(now) + 1):
            a = by_day.get(d) or agg()
            daily.append(finish(day_str(d), a))
            date = dt.date(1970, 1, 1) + dt.timedelta(days=d)
            monday = date - dt.timedelta(days=date.weekday())
            merge(weekly[monday.strftime("%Y-%m-%d")], a)
            merge(monthly[date.strftime("%Y-%m")], a)
            merge(yearly[date.strftime("%Y")], a)

    def rolling(sec):
        a = agg()
        cut = now - sec
        for t in reversed(trades):
            if t["ts"] < cut:
                break
            k = "compra" if t["lado"] == "compra" else "venda"
            a[k + "_usd"] += t["usd"]; a["bnb"] += t["bnb"]; a["tok"] += t["tok"]; a["n_" + k] += 1
            a["compradores" if k == "compra" else "vendedores"].add(t["who"])
        return finish(sec, a)

    # volume por faixa de preço (perfil de volume)
    def profile(sec, nb=48):
        cut = now - sec if sec else 0
        tr = [t for t in trades if t["ts"] >= cut]
        if len(tr) < 2:
            return None
        lo = min(t["preco_usd"] for t in tr); hi = max(t["preco_usd"] for t in tr)
        if hi <= lo:
            return None
        step = (hi - lo) / nb
        bins = [[0.0, 0.0, 0] for _ in range(nb)]
        for t in tr:
            k = min(nb - 1, int((t["preco_usd"] - lo) / step))
            bins[k][0 if t["lado"] == "compra" else 1] += t["usd"]
            bins[k][2] += 1
        tot = [b[0] + b[1] for b in bins]
        total = sum(tot)
        poc = max(range(nb), key=lambda i: tot[i])
        a = b_ = poc
        acc = tot[poc]
        while acc < 0.7 * total and (a > 0 or b_ < nb - 1):      # zona com 70% do volume
            dn = tot[a - 1] if a > 0 else -1
            up = tot[b_ + 1] if b_ < nb - 1 else -1
            if up >= dn:
                b_ += 1; acc += tot[b_]
            else:
                a -= 1; acc += tot[a]
        return {"min": lo, "max": hi, "passo": step, "total": total,
                "faixas": [{"de": lo + i * step, "ate": lo + (i + 1) * step, "compra": bins[i][0], "venda": bins[i][1], "n": bins[i][2]}
                           for i in range(nb)],
                "poc": lo + (poc + 0.5) * step, "poc_usd": tot[poc],
                "zona_min": lo + a * step, "zona_max": lo + (b_ + 1) * step}

    hold_series = []
    if holders_daily:
        ds = sorted(holders_daily)
        last = 0
        for d in range(ds[0], local_day(now) + 1):
            last = holders_daily.get(d, last)
            hold_series.append({"dia": day_str(d), "holders": last, "novos": new_holders_daily.get(d, 0)})
        hold_series = [h for h in hold_series if h["dia"] >= day_str(local_day(launch) - 3)]

    # ------------------------------------------------------------ taxas efetivas (compra/venda)
    def median(v):
        v = sorted(v)
        return v[len(v) // 2] if v else None
    recent = trades[-300:]
    tax_buy = median([t["tax"] for t in recent if t["lado"] == "compra" and t["tax"] is not None])
    tax_sell = median([t["tax"] for t in recent if t["lado"] == "venda" and t["tax"] is not None])
    tax_daily = defaultdict(lambda: {"c": [], "v": []})
    for t in trades:
        if t["tax"] is not None:
            tax_daily[local_day(t["ts"])]["c" if t["lado"] == "compra" else "v"].append(t["tax"])
    tax_series = [{"dia": day_str(d), "compra": median(x["c"]), "venda": median(x["v"])} for d, x in sorted(tax_daily.items())]

    # ------------------------------------------------------------ custo dos holders (suporte/resistência)
    bands = defaultdict(float)
    in_profit = in_loss = no_cost = 0.0
    for a, b in non_pool:
        w = W.get(a)
        if not w or w["qty"] <= DUST:
            continue
        paid_qty = min(b, w["qty"])
        if w["cost"] <= 0:
            no_cost += paid_qty
            continue
        avg = w["cost"] / w["qty"]
        if price and avg > 0:
            r = avg / price
            key = round(math.log(r, 1.25)) if r > 0 else 0   # faixas de 25%
            key = max(-12, min(12, key))
            bands[key] += paid_qty
        if avg <= price:
            in_profit += paid_qty
        else:
            in_loss += paid_qty
    cost_bands = [{"preco": price * 1.25 ** k, "rel": (1.25 ** k - 1) * 100, "tokens": v, "pct": v / total_supply * 100}
                  for k, v in sorted(bands.items())]

    # ------------------------------------------------------------ liquidez e cotas (LP)
    lp_total = sum(v for a, v in lp_bal.items() if a != ZERO and v > 1e-12) or float(meta.get("state_lp_supply") or 0)
    lp_supply = float(meta.get("state_lp_supply") or 0) or (lp_total + max(lp_bal.get(ZERO, 0), 0))
    lp_holders = sorted(({"end": a, "rotulo": label(a) or ("Cota mínima travada" if a == ZERO else ""), "tipo": kind(a),
                          "lp": v, "pct": v / lp_supply * 100 if lp_supply else 0}
                         for a, v in lp_bal.items() if v > 1e-12), key=lambda x: -x["lp"])[:20]
    lp_locked = sum(x["pct"] for x in lp_holders if x["end"] in BURN_ADDRS or "Cofre" in x["rotulo"])
    liq_usd = 2 * r_bnb * bnb_now

    # impacto de preço: quanto o preço cai/sobe ao vender/comprar X dólares (fórmula do pool, sem taxa do token)
    def impact_sell(usd):
        if not price or not r_tok:
            return None
        tok = usd / price
        out = r_bnb * tok * 0.9975 / (r_tok + tok * 0.9975)
        return (out / tok / price_bnb - 1) * 100

    def impact_buy(usd):
        if not bnb_now or not r_bnb:
            return None
        b = usd / bnb_now
        out = r_tok * b * 0.9975 / (r_bnb + b * 0.9975)
        return ((b / out) / price_bnb - 1) * 100
    impacts = [{"usd": u, "venda": impact_sell(u), "compra": impact_buy(u)} for u in (100, 500, 1000, 5000, 10000, 50000)]

    # ------------------------------------------------------------ relação com o BNB
    rel = {}
    hs = [h for h in hours if h[0] >= (launch // 3600) * 3600]
    for name, n in (("24h", 24), ("7d", 168), ("30d", 720), ("tudo", len(hs))):
        seg = hs[-(n + 1):]
        if name == "tudo" and trades and hs:
            # desde o lançamento: começa no preço da 1ª negociação, não no fim da 1ª hora
            t0 = trades[0]
            b0 = bnb_usd(t0["ts"])
            seg = [[t0["ts"], t0["preco_bnb"], t0["preco_bnb"] * b0, b0]] + hs
        if len(seg) < 7:
            continue
        rv = [math.log(seg[i][2] / seg[i - 1][2]) for i in range(1, len(seg))]
        rb = [math.log(seg[i][3] / seg[i - 1][3]) for i in range(1, len(seg))]
        c, beta = corr_beta(rv, rb)
        # correlação dos movimentos de 4 em 4 horas (reduz o ruído de horas sem negociação)
        rv4 = [math.log(seg[i][2] / seg[i - 4][2]) for i in range(4, len(seg), 4)]
        rb4 = [math.log(seg[i][3] / seg[i - 4][3]) for i in range(4, len(seg), 4)]
        c4, _ = corr_beta(rv4, rb4)
        rel[name] = {"corr": c, "beta": beta, "corr4h": c4,
                     "vell_usd": pct(seg[-1][2], seg[0][2]), "bnb_usd": pct(seg[-1][3], seg[0][3]),
                     "vell_bnb": pct(seg[-1][1], seg[0][1])}

    # preço dos outros ativos, alinhado às mesmas horas do VELL (para os gráficos de comparação)
    tok_map = defaultdict(dict)
    for sym, ts_, close in tok_rows:
        tok_map[sym][ts_] = close
    tokens = {"BNB": [h[3] for h in hs], "USDT": [1.0] * len(hs)}
    for sym, mp in tok_map.items():
        keys = sorted(mp)
        serie, last_v = [], None
        for h in hs:
            v = mp.get(h[0])
            if v is None and last_v is None and keys:      # antes do primeiro dado: usa o mais próximo anterior
                k = bisect.bisect_right(keys, h[0]) - 1
                v = mp[keys[k]] if k >= 0 else None
            last_v = v if v is not None else last_v
            serie.append(last_v)
        if any(x is not None for x in serie):
            tokens[sym] = serie

    # mesma tabela de relação, mas contra o BTC (o VELL não é negociado contra BTC; serve como "mercado em geral")
    def rel_for(ref, ref0):
        out_ = {}
        pts = [(h[2], r) for h, r in zip(hs, ref) if r]
        for name, n in (("24h", 24), ("7d", 168), ("30d", 720), ("tudo", len(pts))):
            seg = pts[-(n + 1):]
            if name == "tudo" and trades and pts and ref0:
                seg = [(trades[0]["preco_usd"], ref0)] + pts
            if len(seg) < 7:
                continue
            rv = [math.log(seg[i][0] / seg[i - 1][0]) for i in range(1, len(seg))]
            rb = [math.log(seg[i][1] / seg[i - 1][1]) for i in range(1, len(seg))]
            c, beta = corr_beta(rv, rb)
            rv4 = [math.log(seg[i][0] / seg[i - 4][0]) for i in range(4, len(seg), 4)]
            rb4 = [math.log(seg[i][1] / seg[i - 4][1]) for i in range(4, len(seg), 4)]
            c4, _ = corr_beta(rv4, rb4)
            out_[name] = {"corr": c, "beta": beta, "corr4h": c4,
                          "vell_usd": pct(seg[-1][0], seg[0][0]), "bnb_usd": pct(seg[-1][1], seg[0][1]),
                          "vell_bnb": pct(seg[-1][0] / seg[-1][1], seg[0][0] / seg[0][1])}
        return out_
    rel_all = {"BNB": rel}
    for sym_ in ("BTC", "ETH", "XRP", "SOL", "TRX", "HYPE", "ZEC"):
        if sym_ not in tokens or not tok_map.get(sym_):
            continue
        kb = sorted(tok_map[sym_])
        i0 = bisect.bisect_right(kb, trades[0]["ts"] - 3600) - 1 if trades else -1   # preço no início da hora do lançamento
        rel_all[sym_] = rel_for(tokens[sym_], tok_map[sym_][kb[i0]] if i0 >= 0 else tokens[sym_][0])

    def chg(sec):
        h = price_at(sec)
        return pct(price, h) if h else None

    # ------------------------------------------------------------ destaques automáticos
    sinais = []
    # grandes negociações nas últimas 24h (a partir de C.BIG_TRADE_USD):
    #   compras e vendas -> a maior compra e a maior venda; só vendas -> a última venda grande; só compras -> as 3 últimas compras grandes
    g24 = [t for t in trades if t["ts"] >= now - DAY and t["usd"] >= C.BIG_TRADE_USD]
    gc_ = [t for t in g24 if t["lado"] == "compra"]
    gv_ = [t for t in g24 if t["lado"] == "venda"]
    IR_TR = {"aba": "fluxo", "alvo": "tb-trades", "cfg": {"fluxoPer": "24h"}}

    def txt_trade(t, titulo):
        a_ = t["who"] or ""
        quem_ = f"{a_[:6]}…{a_[-4:]}" if a_ else "carteira desconhecida"
        verbo_ = "comprou" if t["lado"] == "compra" else "vendeu"
        px_ = f"{t['preco_usd']:.6f}".replace(".", ",")
        quando_ = dt.datetime.utcfromtimestamp(t["ts"] + TZ)
        return (f"{titulo}: {quem_} {verbo_} {br(t['tok'])} VELL por US$ {br(t['usd'])} "
                f"às {quando_:%H:%M} de {quando_:%d/%m} (preço US$ {px_}).")
    if gc_ and gv_:
        sinais.append({"tipo": "compra", "txt": txt_trade(max(gc_, key=lambda t: t["usd"]), "Maior compra nas últimas 24h"), "ir": IR_TR})
        sinais.append({"tipo": "venda", "txt": txt_trade(max(gv_, key=lambda t: t["usd"]), "Maior venda nas últimas 24h"), "ir": IR_TR})
    elif gv_:
        sinais.append({"tipo": "venda", "txt": txt_trade(gv_[-1], "Última venda grande (só houve vendas grandes nas últimas 24h)"), "ir": IR_TR})
    elif gc_:
        for t in gc_[-3:][::-1]:
            sinais.append({"tipo": "compra", "txt": txt_trade(t, "Compra grande nas últimas 24h"), "ir": IR_TR})
    for ev in liq_events:
        if ev["ts"] >= now - 7 * DAY and ev["usd"] >= C.BIG_TRADE_USD:
            sinais.append({"tipo": "liquidez", "txt": f"Liquidez: {ev['tipo']} de US$ {br(ev['usd'])} em {dt.datetime.utcfromtimestamp(ev['ts'] + TZ):%d/%m %H:%M}.",
                           "ir": {"aba": "liquidez", "alvo": "tb-liqev"}})
    r24 = rolling(DAY)
    if r24["volume_usd"]:
        # a pressão é decidida pelo valor em US$ negociado, não pelo número de operações
        pc_ = r24["compra_usd"] / r24["volume_usd"] * 100
        pv_ = 100 - pc_
        cont_ = f"US$ {br(r24['compra_usd'])} em {r24['n_compra']} compras x US$ {br(r24['venda_usd'])} em {r24['n_venda']} vendas"
        if abs(pc_ - 50) < 2.5:
            tipo_, txt_ = "fluxo", f"Compras e vendas equilibradas nas últimas 24h: {pc_:.0f}% do valor negociado foi compra ({cont_})."
        elif pc_ > 50:
            tipo_, txt_ = "compra", f"Pressão compradora nas últimas 24h: {pc_:.0f}% do valor negociado foi compra ({cont_})."
        else:
            tipo_, txt_ = "venda", f"Pressão vendedora nas últimas 24h: {pv_:.0f}% do valor negociado foi venda ({cont_})."
        sinais.append({"tipo": tipo_, "txt": txt_,
                       "ir": {"aba": "fluxo", "alvo": "fluxo-kpis", "cfg": {"fluxoPer": "24h"}}})

    # ------------------------------------------------------------ leitura do mercado (placar de sinais)
    H_ts = [h[0] for h in hs]
    T_ts = [t["ts"] for t in trades]
    HC_ts = [x[0] for x in hc]
    PRAZOS = {
        # thr = quanto vale 1 ponto em: (distância da média, variação do preço, variação do BNB no pool, variação de holders)
        "curto": {"h": 24, "nome": "Curto prazo", "janela": "últimas 24 horas", "thr": (0.02, 0.03, 0.01, 0.003), "perfil_h": 168, "fut": 24, "fut_nome": "24 horas"},
        "medio": {"h": 168, "nome": "Médio prazo", "janela": "últimos 7 dias", "thr": (0.06, 0.10, 0.03, 0.015), "perfil_h": 720, "fut": 72, "fut_nome": "3 dias"},
        "longo": {"h": 720, "nome": "Longo prazo", "janela": "últimos 30 dias", "thr": (0.12, 0.20, 0.06, 0.05), "perfil_h": 10 ** 6, "fut": 168, "fut_nome": "7 dias"},
        # prazos de contexto: não entram no filtro do prazo maior; enquanto o VELL tiver menos de 1 ano, usam o histórico que existe
        "anual": {"h": 8760, "nome": "Anual", "janela": "últimos 365 dias", "thr": (0.25, 0.40, 0.12, 0.10), "perfil_h": 10 ** 6, "fut": 168, "fut_nome": "7 dias", "min_i": 72},
        "tudo": {"h": 10 ** 7, "nome": "Desde o lançamento", "janela": "todo o histórico", "thr": (0.25, 0.40, 0.12, 0.10), "perfil_h": 10 ** 6, "fut": 168, "fut_nome": "7 dias", "min_i": 72},
    }
    SINAIS = [("tendencia", "Tendência", 2.0), ("estrutura", "Topos e fundos", 1.0), ("forca", "Força do movimento", 1.5),
              ("fluxo", "Fluxo de compras e vendas", 2.0), ("grandes", "Negociações grandes", 1.5), ("liquidez", "BNB na liquidez", 1.5),
              ("perfil", "Volume por preço", 1.0), ("proprio", "Movimento próprio (VELL em BNB)", 1.0), ("holders", "Holders", 0.5)]
    PESO_TOTAL = sum(x[2] for x in SINAIS)
    ROTULOS = ["ultra pessimista", "pessimista", "neutro", "otimista", "ultra otimista"]

    def clamp(x):
        return max(-2.0, min(2.0, x))

    def rotulo(sc):
        return ROTULOS[4] if sc >= 50 else ROTULOS[3] if sc >= 15 else ROTULOS[2] if sc > -15 else ROTULOS[1] if sc > -50 else ROTULOS[0]

    def fp(x, d=1):
        return f"{x * 100:+.{d}f}%".replace(".", ",")

    def fn(x, d=2):
        return f"{x:.{d}f}".replace(".", ",")

    def holders_at(ts):
        k = bisect.bisect_right(HC_ts, ts) - 1
        return hc[k][1] if k >= 0 else 0

    def ler(i, pz, detalhe=False):
        """Placar no fim da hora i, olhando a janela do prazo. Só usa dados até aquele momento."""
        P = PRAZOS[pz]
        j = i - P["h"]
        if j < 0:
            if i < P.get("min_i", max(24, P["h"] * 0.25)):
                return None
            j = 0
        seg = hs[j:i + 1]
        px, T, T0 = seg[-1][2], seg[-1][0] + 3600, seg[0][0] + 3600
        t1, t2, t3, t4 = P["thr"]
        N, X = {}, {}
        sma = sum(h[2] for h in seg) / len(seg)
        d = px / sma - 1
        N["tendencia"] = clamp(d / t1)
        m = len(seg) // 2
        a, b = seg[:m], seg[m:]
        hi1, hi2 = max(h[8] for h in a), max(h[8] for h in b)
        lo1, lo2 = min(h[9] for h in a), min(h[9] for h in b)
        sg = lambda x, y: 1 if x > y * 1.005 else -1 if x < y * 0.995 else 0
        N["estrutura"] = float(sg(hi2, hi1) + sg(lo2, lo1))
        r = px / seg[0][2] - 1
        N["forca"] = clamp(r / t2)
        ia, ib = bisect.bisect_left(T_ts, T0), bisect.bisect_right(T_ts, T)
        buy = sell = bigb = bigs = 0.0
        nb = ns = 0
        for t in trades[ia:ib]:
            if t["lado"] == "compra":
                buy += t["usd"]; nb += 1
                if t["usd"] >= C.BIG_TRADE_USD:
                    bigb += t["usd"]
            else:
                sell += t["usd"]; ns += 1
                if t["usd"] >= C.BIG_TRADE_USD:
                    bigs += t["usd"]
        vol = buy + sell
        share = buy / vol if vol > 0 else 0.5
        N["fluxo"] = clamp((share - 0.5) / 0.1) if vol >= 50 else 0.0
        N["grandes"] = clamp((bigb - bigs) / (vol * 0.25)) if vol >= 50 and (bigb + bigs) > 0 else 0.0
        lq = seg[-1][6] / seg[0][6] - 1 if seg[0][6] else 0.0
        N["liquidez"] = clamp(lq / t3)
        k0 = bisect.bisect_left(T_ts, T - P["perfil_h"] * 3600)
        tr = trades[k0:ib]
        N["perfil"], poc_px, za, zb = 0.0, None, None, None
        if len(tr) >= 20:
            lo = min(t["preco_usd"] for t in tr); hi = max(t["preco_usd"] for t in tr)
            if hi > lo:
                nbins = 30
                step = (hi - lo) / nbins
                tot = [0.0] * nbins
                for t in tr:
                    tot[min(nbins - 1, int((t["preco_usd"] - lo) / step))] += t["usd"]
                pk = max(range(nbins), key=lambda q: tot[q])
                qa = qb = pk
                acc, alvo = tot[pk], 0.7 * sum(tot)
                while acc < alvo and (qa > 0 or qb < nbins - 1):
                    dn = tot[qa - 1] if qa > 0 else -1
                    up = tot[qb + 1] if qb < nbins - 1 else -1
                    if up >= dn:
                        qb += 1; acc += tot[qb]
                    else:
                        qa -= 1; acc += tot[qa]
                poc_px, za, zb = lo + (pk + 0.5) * step, lo + qa * step, lo + (qb + 1) * step
                N["perfil"] = 2.0 if px > zb else -2.0 if px < za else 1.0 if px >= poc_px else -1.0
        rb = seg[-1][1] / seg[0][1] - 1
        N["proprio"] = clamp(rb / t2)
        n1, n0 = holders_at(T), holders_at(T0)
        hch = (n1 - n0) / n0 if n0 else 0.0
        N["holders"] = clamp(hch / t4)
        score = sum(N[k] * w for k, _, w in SINAIS) / (2 * PESO_TOTAL) * 100
        if not detalhe:
            return score
        X["tendencia"] = f"Preço {fp(abs(d))[1:]} {'acima' if d >= 0 else 'abaixo'} da média do período."
        X["estrutura"] = {2: "Topos e fundos mais altos na segunda metade do período.", -2: "Topos e fundos mais baixos na segunda metade do período.",
                          1: "Topos ou fundos subindo, sem confirmação dos dois.", -1: "Topos ou fundos descendo, sem confirmação dos dois.",
                          0: "Topos e fundos sem direção clara."}[int(N["estrutura"])]
        X["forca"] = f"Preço variou {fp(r)} no período."
        if vol >= 50:
            X["fluxo"] = f"{share * 100:.0f}% do volume foi compra (US$ {br(buy)} em {nb} compras contra US$ {br(sell)} em {ns} vendas)."
        else:
            X["fluxo"] = "Volume muito baixo no período para avaliar."
        if (bigb + bigs) > 0:
            X["grandes"] = f"Negociações de US$ {br(C.BIG_TRADE_USD)} ou mais: US$ {br(bigb)} em compras e US$ {br(bigs)} em vendas."
        else:
            X["grandes"] = "Nenhuma negociação grande no período."
        X["liquidez"] = f"BNB no pool variou {fp(lq, 2)} (de {fn(seg[0][6])} para {fn(seg[-1][6])} BNB)."
        if poc_px:
            if px > zb:
                onde = "acima da zona de maior volume"
            elif px < za:
                onde = "abaixo da zona de maior volume"
            elif px >= poc_px:
                onde = "dentro da zona de maior volume, acima do preço mais negociado"
            else:
                onde = "dentro da zona de maior volume, abaixo do preço mais negociado"
            X["perfil"] = f"Preço {onde} (mais negociado: US$ {fn(poc_px, 5)}; zona: US$ {fn(za, 5)} a US$ {fn(zb, 5)})."
        else:
            X["perfil"] = "Poucas negociações para montar o volume por preço."
        X["proprio"] = f"VELL medido em BNB variou {fp(rb)} no período."
        X["holders"] = f"Holders foram de {br(n0)} para {br(n1)} ({fp(hch, 2)})."
        return {"score": round(score, 1), "rotulo": rotulo(score), "nome": P["nome"], "janela": P["janela"],
                "sinais": [{"id": k, "nome": nm, "peso": w, "nota": round(N[k], 2), "txt": X[k]} for k, nm, w in SINAIS]}

    # Filtro: um prazo menor não pode contrariar um prazo maior que esteja no extremo.
    # Ex.: se os últimos 7 dias estão "ultra pessimista", as últimas 24 horas chegam no máximo a "neutro".
    def limitar(sc, maior):
        if sc is None or maior is None:
            return sc
        if maior <= -50 and sc > 14:
            return 14.0
        if maior >= 50 and sc < -14:
            return -14.0
        return sc

    def bruto(i, pz, last_i):
        ck = (hs[i][0], pz)
        if i < last_i and ck in _LEITURA_CACHE:     # horas já fechadas não mudam: reaproveita
            return _LEITURA_CACHE[ck]
        sc = ler(i, pz)
        if i < last_i:
            _LEITURA_CACHE[ck] = sc
        return sc

    def ajustados(i, last_i):
        b = {pz: bruto(i, pz, last_i) for pz in PRAZOS}
        a = {"longo": b["longo"]}
        a["medio"] = limitar(b["medio"], a["longo"])
        a["curto"] = limitar(b["curto"], a["medio"])
        a["anual"], a["tudo"] = b["anual"], b["tudo"]
        return b, a

    leitura = {"prazos": {}, "historico": [], "teste": {}, "rotulos": ROTULOS}
    if len(hs) > 30:
        last_i = len(hs) - 1
        b_now, a_now = ajustados(last_i, last_i)
        maior_de = {"curto": "medio", "medio": "longo"}
        for pz in PRAZOS:
            r_ = ler(last_i, pz, True)
            if r_:
                r_["score_bruto"] = r_["score"]
                if a_now[pz] is not None and abs(a_now[pz] - r_["score"]) > 0.05:
                    r_["score"] = round(a_now[pz], 1)
                    r_["rotulo"] = rotulo(a_now[pz])
                    r_["ajuste"] = (f"Os sinais deste prazo dariam \"{rotulo(r_['score_bruto'])}\", mas a leitura foi limitada a "
                                    f"\"{r_['rotulo']}\" porque o {PRAZOS[maior_de[pz]]['nome'].lower()} está no extremo oposto.")
                leitura["prazos"][pz] = r_
        amostras = sorted(set(list(range(24, len(hs), 6)) + [last_i]))
        buckets = {pz: {rt: [] for rt in ROTULOS} for pz in PRAZOS}
        buckets_b = {pz: {rt: [] for rt in ROTULOS} for pz in PRAZOS}
        mudou = {pz: 0 for pz in PRAZOS}
        for i in amostras:
            b_, a_ = ajustados(i, last_i)
            linha = [hs[i][0] + 3600, hs[i][2]]
            for pz, P in PRAZOS.items():
                sc = a_[pz]
                linha.append(None if sc is None else round(sc, 1))
                if sc is not None and rotulo(sc) != rotulo(b_[pz]):
                    mudou[pz] += 1
                if sc is not None and i + P["fut"] < len(hs):
                    fwd = hs[i + P["fut"]][2] / hs[i][2] - 1
                    buckets[pz][rotulo(sc)].append(fwd)
                    buckets_b[pz][rotulo(b_[pz])].append(fwd)
            leitura["historico"].append(linha)      # [quando, preço, curto, médio, longo, anual, desde o lançamento]

        def resumo(bk):
            linhas = []
            for rt in ROTULOS[::-1]:
                v = sorted(bk[rt])
                linhas.append({"rotulo": rt, "n": len(v), "subiu_pct": (sum(1 for x in v if x > 0) / len(v) * 100) if v else None,
                               "media": (sum(v) / len(v) * 100) if v else None, "mediana": (v[len(v) // 2] * 100) if v else None})
            return linhas
        for pz, P in PRAZOS.items():
            linhas = resumo(buckets[pz])
            leitura["teste"][pz] = {"depois": P["fut_nome"], "n": sum(x["n"] for x in linhas), "linhas": linhas,
                                    "sem_filtro": resumo(buckets_b[pz]), "mudou": mudou[pz]}

    # ------------------------------------------------------------ destaques automáticos (continuação)
    def quando(ts):
        return f"{dt.datetime.utcfromtimestamp(ts + TZ):%d/%m às %H:%M}"

    def pcs(x):
        return f"{x:+.1f}%".replace(".", ",")

    # 1) mudança na leitura do mercado
    Hh = leitura["historico"]
    if Hh:
        novas, seguem = [], None
        for ci, pz in ((2, "curto"), (3, "medio"), (4, "longo")):
            s_ = [(x[0], rotulo(x[ci])) for x in Hh if x[ci] is not None]
            if len(s_) < 2:
                continue
            k = len(s_) - 1
            while k > 0 and s_[k - 1][1] == s_[-1][1]:
                k -= 1
            if k > 0 and s_[k][0] >= now - DAY:
                novas.append((pz, s_[k - 1][1], s_[-1][1], s_[k][0]))
            elif pz == "curto" and k > 0:
                seguem = (s_[-1][1], s_[k][0])
        for pz, de, para, ts_ in novas:
            sinais.append({"tipo": "compra" if ROTULOS.index(para) > ROTULOS.index(de) else "venda",
                           "txt": f"A leitura de {PRAZOS[pz]['nome'].lower()} mudou de {de} para {para} ({quando(ts_)}).",
                           "ir": {"aba": "leitura", "alvo": "lei-cards", "cfg": {"leiPz": pz}}})
        if not novas and seguem:
            sinais.append({"tipo": "fluxo", "txt": f"A leitura de curto prazo segue {seguem[0]} desde {quando(seguem[1])}.",
                           "ir": {"aba": "leitura", "alvo": "lei-cards", "cfg": {"leiPz": "curto"}}})

    # 2) preço contra o custo dos holders de curto prazo (comprou nos últimos 7 dias)
    S7 = sth.get("7d")
    if S7 and S7["agora"]["custo"] and S7["agora"]["preco"]:
        c_, px_ = S7["agora"]["custo"], S7["agora"]["preco"]
        acima = px_ >= c_
        ser_ = S7["serie"]
        ont = ser_[-2] if len(ser_) >= 2 else None
        if ont and ont["custo"] and ont["preco"] and (ont["preco"] >= ont["custo"]) != acima:
            txt = (f"O preço (US$ {fn(px_, 5)}) passou {'acima' if acima else 'abaixo'} do custo médio de quem comprou nos últimos 7 dias "
                   f"(US$ {fn(c_, 5)}): esses holders {'voltaram ao lucro' if acima else 'entraram no prejuízo'}.")
        else:
            txt = (f"O preço está {pcs(abs(px_ / c_ - 1) * 100)[1:]} {'acima' if acima else 'abaixo'} do custo médio de quem comprou nos últimos 7 dias "
                   f"(US$ {fn(c_, 5)}): em média esses holders estão no {'lucro' if acima else 'prejuízo'}.")
        sinais.append({"tipo": "compra" if acima else "venda", "txt": txt, "ir": {"aba": "leitura", "alvo": "sth-kpis", "cfg": {"sthK": "7d"}}})

    # 3) holders entrando e saindo
    ent = sum(1 for t_, x in hio if t_ >= now - DAY and x > 0)
    sai = sum(1 for t_, x in hio if t_ >= now - DAY and x < 0)
    if ent or sai:
        liq_ = ent - sai
        sinais.append({"tipo": "compra" if liq_ > 0 else "venda" if liq_ < 0 else "fluxo",
                       "txt": f"Nas últimas 24h, {br(ent)} carteiras passaram a ter VELL e {br(sai)} zeraram o saldo (saldo de {br(liq_, True)} holders).",
                       "ir": {"aba": "carteiras", "alvo": "c-hold"}})

    # 4) movimento próprio do VELL contra o mercado
    # mesmo cálculo do cartão "Variação 24 horas": momento exato de 24h atrás, BNB do minuto
    k24 = bisect.bisect_right(sync_ts, now - DAY) - 1
    bnb24 = bnb_usd(now - DAY)
    if k24 >= 0 and syncs[k24][1] and bnb24 and price_bnb:
        v_usd = chg(DAY)
        v_bnb = pct(bnb_now, bnb24)
        vb = pct(price_bnb, syncs[k24][2] / syncs[k24][1])
        btc_ = ((rel_all.get("BTC") or {}).get("24h") or {}).get("bnb_usd")
        txt = f"Em 24h o VELL variou {pcs(v_usd)} e o BNB {pcs(v_bnb)}" + (f" (BTC {pcs(btc_)})" if btc_ is not None else "") + ". "
        if abs(vb) >= abs(v_bnb):
            txt += f"A maior parte do movimento veio do próprio VELL ({pcs(vb)} medido em BNB), não do mercado."
        else:
            txt += f"O VELL acompanhou mais o mercado do que se moveu sozinho ({pcs(vb)} medido em BNB)."
        sinais.append({"tipo": "compra" if vb > 0 else "venda" if vb < 0 else "fluxo", "txt": txt, "ir": {"aba": "bnb", "alvo": "tb-bnb", "cfg": {"relRef": "BNB"}}})

    # 5) vendas de holders de longo prazo (VELL parado há mais de 7 dias)
    L7 = lth.get("7d")
    IR_LTH = {"aba": "leitura", "alvo": "lth-kpis", "cfg": {"lthK": "7d"}}
    if L7:
        # últimas 24h corridas x média por dia dos 7 dias anteriores a elas
        hoje_v = L7["agora"]["vendido24_usd"]
        media_ = L7["agora"]["media_dia_ant_usd"]
        if media_ > 0 and hoje_v >= 2 * media_ and hoje_v >= 50:
            sinais.append({"tipo": "venda", "txt": f"Holders de longo prazo (VELL parado há mais de 7 dias) venderam US$ {br(hoje_v)} nas últimas 24h, "
                                                   f"{fn(hoje_v / media_, 1)}x a média diária dos 7 dias anteriores (US$ {br(media_)}).", "ir": IR_LTH})
        elif hoje_v > 0 or media_ > 0:
            sinais.append({"tipo": "venda" if hoje_v > media_ else "compra",
                           "txt": f"Holders de longo prazo (VELL parado há mais de 7 dias) venderam US$ {br(hoje_v)} nas últimas 24h "
                                  f"(média diária dos 7 dias anteriores: US$ {br(media_)}).", "ir": IR_LTH})

    # ------------------------------------------------------------ queimas (VELL enviado ao endereço morto/zero)
    def q_janela(sec):
        b_ = [b for b in burns if b[0] >= now - sec]
        return {"qtd": sum(b[2] for b in b_), "n": len(b_), "usd": sum(b[2] * (b[4] or 0) for b in b_),
                "pct": sum(b[2] for b in b_) / total_supply * 100, "carteiras": len({b[1] for b in b_})}
    q_dia = defaultdict(lambda: [0.0, 0, 0.0])          # por dia: [VELL, nº de queimas, US$ na hora]
    q_quem = {}
    for ts_, f_, v_, tx_, px_ in burns:
        x_ = q_dia[local_day(ts_)]; x_[0] += v_; x_[1] += 1; x_[2] += v_ * (px_ or 0)
        w_ = q_quem.get(f_)
        if w_ is None:
            w_ = q_quem[f_] = {"end": f_, "rotulo": label(f_), "tipo": kind(f_), "n": 0, "qtd": 0.0, "usd": 0.0, "primeira": ts_, "ultima": ts_}
        w_["n"] += 1; w_["qtd"] += v_; w_["usd"] += v_ * (px_ or 0); w_["ultima"] = ts_
    q_total = sum(b[2] for b in burns)
    q_serie, acum_ = [], 0.0
    if burns:
        for d_ in range(local_day(burns[0][0]), local_day(now) + 1):
            x_ = q_dia.get(d_, [0.0, 0, 0.0]); acum_ += x_[0]
            q_serie.append({"dia": day_str(d_), "qtd": x_[0], "n": x_[1], "usd": x_[2], "acum": acum_, "pct_acum": acum_ / total_supply * 100})
    for w_ in q_quem.values():
        w_["pct"] = w_["qtd"] / q_total * 100 if q_total else 0
    q_auto = sum(w_["qtd"] for w_ in q_quem.values() if w_["tipo"] == "contrato")
    q7, q30 = q_janela(7 * DAY), q_janela(30 * DAY)
    ritmo_ = q30["qtd"] / min(30.0, max(1.0, (now - burns[0][0]) / DAY)) if burns else 0.0
    queimas = {
        "total": q_total, "pct": q_total / total_supply * 100, "n": len(burns), "usd_agora": q_total * price,
        "usd_na_hora": sum(b[2] * (b[4] or 0) for b in burns), "carteiras": len(q_quem),
        "primeira": burns[0][0] if burns else None, "ultima": burns[-1][0] if burns else None,
        "automatica": q_auto, "manual": q_total - q_auto,
        "24h": q_janela(DAY), "7d": q7, "30d": q30, "365d": q_janela(365 * DAY), "tudo": q_janela(now),
        "ritmo_dia": ritmo_, "proj_ano_pct": ritmo_ * 365 / total_supply * 100,
        "saldo_morto": max(bal.get(DEAD, 0.0), 0.0), "saldo_zero": max(bal.get(ZERO, 0.0), 0.0),
        "serie": q_serie,
        "quem": sorted(q_quem.values(), key=lambda w: -w["qtd"])[:40],
        # últimas queimas, compactas: [quando, quem, VELL, US$ na hora, transação]
        "recentes": [[b[0], b[1], round(b[2], 4), round(b[2] * (b[4] or 0), 4), b[3]] for b in burns[-500:][::-1]],
        "maiores": [[b[0], b[1], round(b[2], 4), round(b[2] * (b[4] or 0), 4), b[3]] for b in sorted(burns, key=lambda b: -b[2])[:30]],
    }
    q24 = queimas["24h"]
    if burns:
        sinais.append({"tipo": "fluxo", "txt": f"Queima: {br(q24['qtd'])} VELL (US$ {br(q24['usd'])}) queimados nas últimas 24h em {q24['n']} queimas. "
                                               f"Total já queimado: {br(q_total)} VELL ({fn(q_total / total_supply * 100, 3)}% do fornecimento).",
                       "ir": {"aba": "queimas", "alvo": "qm-kpis"}})

    def trade_out(t):
        a = t["who"] or ""
        return {"ts": t["ts"], "lado": t["lado"], "tok": t["tok"], "bnb": t["bnb"], "usd": t["usd"],
                "preco": t["preco_usd"], "quem": a, "rotulo": label(a), "tx": t["tx"],
                "saldo": max(bal.get(a, 0.0), 0.0), "taxa": t["tax"]}

    out = {
        "gerado_em": now, "ultima_coleta": int(meta.get("last_update") or 0), "ultimo_bloco": int(meta.get("last_block") or 0),
        "simbolo": C.SYMBOL, "token": C.TOKEN, "par": C.PAIR, "tz": C.TZ_OFFSET_HOURS, "dia_tz": DTZ // 3600, "lancamento": launch,
        "resumo": {
            "preco": price, "preco_bnb": price_bnb, "bnb_usd": bnb_now,
            "var_1h": chg(3600), "var_24h": chg(DAY), "var_7d": chg(7 * DAY), "var_30d": chg(30 * DAY),
            "var_lancamento": pct(price, trades[0]["preco_usd"]) if trades else None,
            "preco_lancamento": trades[0]["preco_usd"] if trades else None,
            "valor_mercado": price * circulating, "fdv": price * total_supply,
            "supply": total_supply, "circulante": circulating, "queimado": total_supply - circulating,
            "liquidez_usd": liq_usd, "reserva_tok": r_tok, "reserva_bnb": r_bnb,
            "liq_sobre_mcap": liq_usd / (price * circulating) * 100 if price else None,
            "holders": holders_n, "n_trades": len(trades),
            "maxima": max((h[2] for h in hs), default=None), "minima": min((h[2] for h in hs), default=None),
        },
        "sinais": sinais,
        "horas": [[h[0], h[2], h[1], h[3], h[4]] for h in hs],      # ts, vell_usd, vell_bnb, bnb_usd, liquidez_usd
        "velas": [[h[0], h[7], h[8], h[9], h[2]] for h in hs],          # ts, abertura, máxima, mínima, fechamento (US$)
        "volume": {
            "rolante": {"24h": r24, "7d": rolling(7 * DAY), "30d": rolling(30 * DAY), "365d": rolling(365 * DAY)},
            "diario": daily,
            "semanal": [finish(k, v) for k, v in sorted(weekly.items())],
            "mensal": [finish(k, v) for k, v in sorted(monthly.items())],
            "anual": [finish(k, v) for k, v in sorted(yearly.items())],
            "calor": heat,
            "perfil": {"24h": profile(DAY), "7d": profile(7 * DAY), "30d": profile(30 * DAY),
                       "mes": profile(sec_mes), "ano": profile(sec_ano), "tudo": profile(0)},
        },
        "carteiras": {
            "top": top, "holders_serie": hold_series,
            "concentracao": {"top10": share(10), "top20": share(20), "top50": share(50), "top100": share(100),
                             "pool_pct": max(bal.get(C.PAIR, 0), 0) / total_supply * 100,
                             "contrato_pct": max(bal.get(C.TOKEN, 0), 0) / total_supply * 100,
                             "cofre_pct": sum(max(bal.get(a, 0), 0) for a, n in KNOWN.items() if "Cofre" in n) / total_supply * 100},
            "faixas": [{"faixa": k, "n": tiers[k][0], "tokens": tiers[k][1], "pct": tiers[k][1] / total_supply * 100}
                       for k in ("baleia", "tubarão", "peixe", "camarão")],
            "mov_24h": movers(d24), "mov_7d": movers(d7), "mov_30d": movers(d30),
            "mov_mes": movers(dmes), "mov_ano": movers(dano), "mov_tudo": movers(dtudo),
            "lucro_top": pnl[:25], "lucro_pior": pnl[-25:][::-1],
            "grupos": clusters[:25],
            "iniciais": {"lista": insiders[:60], "n": len(insiders), "recebido": ins_recv, "saldo": ins_bal,
                         "pct_recebido": ins_recv / total_supply * 100, "pct_saldo": ins_bal / total_supply * 100,
                         "vendido_usd": sum(x["vendeu_usd"] for x in insiders)},
            "custo": {"faixas": cost_bands, "em_lucro": in_profit, "em_prejuizo": in_loss, "sem_custo": no_cost,
                      "pct_lucro": in_profit / total_supply * 100, "pct_prejuizo": in_loss / total_supply * 100,
                      "pct_sem_custo": no_cost / total_supply * 100},
        },
        "fluxo": {
            "recentes": [trade_out(t) for t in trades[-400:][::-1]],
            "grandes": [trade_out(t) for t in sorted(trades, key=lambda t: -t["usd"])[:60]],
            # todas as negociações, compactas: [quando, 1=compra/0=venda, VELL, BNB, US$, preço, carteira, transação, taxa]
            "todas": [[t["ts"], 1 if t["lado"] == "compra" else 0, round(t["tok"], 2), round(t["bnb"], 6), round(t["usd"], 2),
                       t["preco_usd"], t["who"] or "", t["tx"], None if t["tax"] is None else round(t["tax"], 4)] for t in trades],
            "saldos": {a: round(max(bal.get(a, 0.0), 0.0), 2) for a in {t["who"] for t in trades if t["who"]}},
            "rotulos": {a: label(a) for a in {t["who"] for t in trades if t["who"]} if label(a)},
            "taxa_compra": tax_buy, "taxa_venda": tax_sell, "taxa_serie": tax_series,
        },
        "queimas": queimas,
        "liquidez": {
            "eventos": liq_events[::-1][:100], "lp_holders": lp_holders, "lp_travado_pct": lp_locked,
            "impacto": impacts, "dono": owner, "criador": deployer, "trocas_dono": owner_changes,
            "dono_saldo": max(bal.get(owner, 0.0), 0.0) if owner else 0.0,
            "dono_renunciou": owner in (ZERO, DEAD) if owner else None,
            "outros_eventos": sum(other_events.values()),
        },
        "indicacao": {"codigo": getattr(C, "REF_CODIGO", ""), "android": getattr(C, "REF_ANDROID", ""), "ios": getattr(C, "REF_IOS", "")},
        "leitura": leitura,
        "sth": sth,
        "lth": lth,
        "bnb": rel,
        "rel": rel_all,
        "tokens": tokens,
        "tempo_calculo": round(time.time() - t_start, 2),
    }
    # histórico por carteira, dividido em arquivos pelos 2 primeiros caracteres do endereço (api/cart/xx)
    shards = defaultdict(dict)
    for a_, ev_ in cart_ev.items():
        if a_ in carteiras_idx:
            shards[a_[2:4]][a_] = ev_
    out["_cart_ev"] = dict(shards)
    out["_carteiras"] = {"gerado_em": now, "preco": price, "campos": CAMPOS_CART, "c": carteiras_idx}
    out["_enderecos_top"] =[a for a, _ in holders[:150]] + [x["end"] for x in insiders[:60]]
    return out


if __name__ == "__main__":
    d = build()
    if d.get("vazio"):
        print("Banco vazio. Rode primeiro:  python coletor.py")
    else:
        r = d["resumo"]
        print(f"Preço US$ {r['preco']:.6f} | 24h {(r['var_24h'] or 0):+.1f}% | liquidez US$ {r['liquidez_usd']:,.0f} | "
              f"holders {r['holders']} | negociações {r['n_trades']} | cálculo {d['tempo_calculo']}s")
        print(json.dumps(d["volume"]["rolante"]["24h"], ensure_ascii=False))
