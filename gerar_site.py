"""Gera a versão online do painel (arquivos estáticos para o GitHub Pages).

Faz o mesmo que o servidor faz a cada atualização: busca os eventos novos na
blockchain, calcula as métricas e grava o resultado. Em vez de servir pela porta
8765, escreve os arquivos numa pasta:

    <saida>/index.html        o painel
    <saida>/logo.jpg
    <saida>/api/dados         as métricas (o mesmo JSON de /api/dados)
    <saida>/api/status        quando foi a última atualização
    <saida>/api/carteiras     todas as carteiras (consulta de lucro/prejuízo)

Uso:  python gerar_site.py _site
"""
import json, os, shutil, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vellcfg as C
import coletor, metricas


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, default=lambda o: None).encode("utf-8")


def calcular():
    data = metricas.build()
    return data, data.pop("_enderecos_top", [])


def main(saida):
    os.makedirs(os.path.join(saida, "api"), exist_ok=True)
    erro = ""
    try:
        coletor.update(lambda i, t, tot: coletor.log(f"histórico: parte {i} de {t} ({tot} eventos)"))
    except Exception as e:                        # sem dados novos, publica o que já está salvo
        erro = "Falha ao buscar dados novos: " + repr(e)[:250]
        coletor.log(erro)
    data, addrs = calcular()
    con = coletor.db()
    try:
        antes = con.execute("SELECT COUNT(*) FROM addr_info").fetchone()[0]
        coletor.check_contracts(con, addrs)
        depois = con.execute("SELECT COUNT(*) FROM addr_info").fetchone()[0]
    finally:
        con.close()
    if depois != antes:
        data, _ = calcular()

    cart = data.pop("_carteiras", {"c": {}})
    with open(os.path.join(saida, "api", "dados"), "wb") as f:
        f.write(dump(data))
    with open(os.path.join(saida, "api", "carteiras"), "wb") as f:
        f.write(json.dumps(cart, ensure_ascii=False, allow_nan=False, separators=(",", ":"), default=lambda o: None).encode("utf-8"))
    status = {"status": "erro" if erro else "ok", "detalhe": "", "erro": erro, "ok_em": int(time.time()),
              "intervalo": int(os.environ.get("VELL_INTERVALO_SITE") or 600)}
    with open(os.path.join(saida, "api", "status"), "wb") as f:
        f.write(dump(status))
    shutil.copyfile(os.path.join(C.BASE_DIR, "painel.html"), os.path.join(saida, "index.html"))
    shutil.copyfile(os.path.join(C.BASE_DIR, "logo.jpg"), os.path.join(saida, "logo.jpg"))
    open(os.path.join(saida, ".nojekyll"), "w").close()
    coletor.log(f"Site gerado em {saida} ({len(data.get('fluxo', {}).get('todas', []))} negociações)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "_site")
