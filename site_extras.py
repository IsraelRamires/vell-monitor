"""Páginas institucionais e arquivos exigidos para monetizar o site (Google AdSense).

Usado por gerar_site.py (site online) e servidor.py (painel local).

Configuração por variáveis de ambiente (no GitHub: Settings > Secrets and variables > Actions > Variables):
    VELL_SITE_URL       endereço público do site, ex.: https://www.monitorvell.com.br
    VELL_ADSENSE_ID     código do editor no AdSense, ex.: ca-pub-1234567890123456
    VELL_EMAIL_CONTATO  e-mail mostrado na página de contato
"""
import html, os, time

URL_PADRAO = "https://israelramires.github.io/vell-monitor"
REPO = "https://github.com/IsraelRamires/vell-monitor"


def cfg():
    pub = (os.environ.get("VELL_ADSENSE_ID") or "").strip()
    if pub and not pub.startswith("ca-pub-"):
        pub = "ca-" + pub if pub.startswith("pub-") else "ca-pub-" + pub
    return {
        "url": (os.environ.get("VELL_SITE_URL") or URL_PADRAO).strip().rstrip("/"),
        "adsense": pub,
        "email": (os.environ.get("VELL_EMAIL_CONTATO") or "").strip(),
    }


def adsense_tag(c=None):
    c = c or cfg()
    if not c["adsense"]:
        return ""
    return (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={c["adsense"]}" '
            f'crossorigin="anonymous"></script>\n<meta name="google-adsense-account" content="{c["adsense"]}">\n')


RODAPE = """<footer class="rodape">
  <nav><a href="./">Painel</a> · <a href="sobre.html">Sobre e guia</a> · <a href="privacidade.html">Privacidade</a> · <a href="termos.html">Termos de uso</a> · <a href="contato.html">Contato</a></nav>
  <p>Este site mostra dados públicos da blockchain apenas para fins informativos e educativos. Nada aqui é recomendação de compra, venda ou investimento. Criptomoedas são de alto risco: você pode perder todo o valor investido.</p>
  <p class="autoria">Produzido por Ramires Corporation © 2026</p>
</footer>"""

CSS_RODAPE = """.rodape{border-top:1px solid #262a33;margin-top:30px;padding:18px 20px 26px;color:#9aa0aa;font-size:12.5px;text-align:center}
.rodape nav{display:block;border:0;padding:0;margin-bottom:6px}.rodape a{color:#9db4ff}
.rodape p{max-width:820px;margin:0 auto}.rodape .autoria{margin-top:8px;color:#f7b500;font-weight:700}
#cookies{position:fixed;left:12px;right:12px;bottom:12px;z-index:30;display:none;gap:12px;align-items:center;flex-wrap:wrap;max-width:760px;margin:0 auto;background:#171a21;border:1px solid #4a5060;border-radius:12px;padding:12px 14px;font-size:13px;color:#c8ccd4;box-shadow:0 8px 24px rgba(0,0,0,.5)}
#cookies.on{display:flex}#cookies span{flex:1 1 300px}#cookies a{color:#9db4ff}
#cookies button{background:#2ec4a6;color:#0f1115;border:0;border-radius:8px;padding:8px 16px;font:inherit;font-weight:700;cursor:pointer}"""

AVISO_COOKIES = """<div id="cookies" role="dialog" aria-label="Aviso de cookies"><span>Usamos cookies e armazenamento local para lembrar suas preferências e, com parceiros como o Google, para exibir anúncios. Saiba mais na <a href="privacidade.html">Política de Privacidade</a>.</span><button onclick="try{localStorage.setItem('vell_cookies','1')}catch(e){};this.parentNode.classList.remove('on')">Entendi</button></div>
<script>try{if(!localStorage.getItem('vell_cookies'))document.getElementById('cookies').classList.add('on')}catch(e){document.getElementById('cookies').classList.add('on')}</script>"""


def montar_painel(texto, c=None):
    """Acrescenta ao painel: metatags, código do AdSense, rodapé e aviso de cookies."""
    c = c or cfg()
    desc = ("Monitor do token VELL na BNB Smart Chain: preço, liquidez, holders de curto e longo prazo, "
            "compras e vendas, queimas e lucro ou prejuízo por carteira, atualizado a cada 10 minutos.")
    head = (f'<meta name="description" content="{desc}">\n'
            f'<link rel="canonical" href="{c["url"]}/">\n'
            f'<meta property="og:title" content="Monitor Token VELL">\n'
            f'<meta property="og:description" content="{desc}">\n'
            f'<meta property="og:image" content="{c["url"]}/logo.jpg">\n'
            f'<meta property="og:url" content="{c["url"]}/">\n'
            f'<link rel="icon" href="logo.jpg">\n'
            + adsense_tag(c) + f"<style>{CSS_RODAPE}</style>\n")
    texto = texto.replace("</head>", head + "</head>", 1)
    return texto.replace("</body>", RODAPE + "\n" + AVISO_COOKIES + "\n</body>", 1)


def _pagina(titulo, desc, corpo, c):
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo} · Monitor Token VELL</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{c["url"]}/{titulo_arquivo(titulo)}">
<link rel="icon" href="logo.jpg">
{adsense_tag(c)}<style>
body{{margin:0;background:#0f1115;color:#e8eaee;font:15px/1.65 "Segoe UI",system-ui,sans-serif}}
header{{display:flex;align-items:center;gap:12px;padding:14px 20px;border-bottom:1px solid #262a33}}
header img{{width:36px;height:36px;border-radius:9px}}header a{{color:#e8eaee;font-weight:700;font-size:17px;text-decoration:none}}header a span{{color:#ff4d4f}}
main{{max-width:820px;margin:0 auto;padding:22px 20px 10px}}
h1{{font-size:26px;margin:6px 0 14px}}h2{{font-size:19px;margin:28px 0 6px}}h3{{font-size:16px;margin:18px 0 4px}}
p,li{{color:#c8ccd4}}a{{color:#9db4ff}}b{{color:#e8eaee}}
.botao{{display:inline-block;background:#2ec4a6;color:#0f1115;font-weight:700;border-radius:9px;padding:9px 16px;text-decoration:none;margin-top:6px}}
.mut{{color:#9aa0aa;font-size:13px}}
{CSS_RODAPE}
</style>
</head>
<body>
<header><img src="logo.jpg" alt="Símbolo do VELL"><a href="./">MONITOR TOKEN <span>VELL</span></a></header>
<main>
{corpo}
</main>
{RODAPE}
{AVISO_COOKIES}
</body>
</html>
"""


def titulo_arquivo(titulo):
    return {"Sobre e guia": "sobre.html", "Política de Privacidade": "privacidade.html",
            "Termos de uso": "termos.html", "Contato": "contato.html"}[titulo]


def paginas(c=None):
    """Devolve {nome_do_arquivo: conteúdo} com todas as páginas e arquivos extras do site."""
    c = c or cfg()
    hoje = time.strftime("%d/%m/%Y")
    pg = {}

    pg["sobre.html"] = _pagina("Sobre e guia", "O que é o Monitor Token VELL e como ler cada métrica do painel.", """
<h1>Sobre o Monitor Token VELL</h1>
<p>O Monitor Token VELL é um painel independente e gratuito que acompanha o token <b>VELL</b> na <b>BNB Smart Chain (BSC)</b>. Ele lê diretamente da blockchain todas as negociações, transferências, queimas e movimentações de liquidez do token, calcula as métricas e publica o resultado aqui, com atualização a cada cerca de 10 minutos.</p>
<p>Todos os dados vêm de fontes públicas: os registros da própria blockchain. Não há dados privados de ninguém. O objetivo é dar a qualquer pessoa — holder, curioso ou pesquisador — uma visão clara e verificável do que está acontecendo com o token, sem precisar ler transações uma a uma num explorador de blocos.</p>
<p>O painel não é ligado a nenhuma corretora e não vende nada. <b>Não é recomendação de investimento</b>: ele mostra números, e a decisão sobre o que fazer com eles é sempre sua.</p>
<a class="botao" href="./">Abrir o painel</a>

<h2>Guia rápido das métricas</h2>

<h3>Preço e liquidez</h3>
<p>O preço do VELL vem do pool de liquidez onde ele é negociado: é a proporção entre os VELL e os BNB guardados no pool, convertida para dólar pelo preço do BNB. A <b>liquidez</b> é o valor total guardado no pool. Quanto maior a liquidez, menos o preço se mexe a cada compra ou venda — por isso o painel mostra também o <b>impacto no preço por tamanho da ordem</b>, isto é, quanto o preço andaria se alguém comprasse ou vendesse um determinado valor de uma vez.</p>

<h3>Compras, vendas e saldo líquido</h3>
<p>Cada troca no pool é classificada como compra (alguém entregou BNB e recebeu VELL) ou venda (o contrário). Somando por dia, semana, mês e ano, o painel mostra o volume e o <b>saldo líquido</b> (compras menos vendas). Saldo positivo por vários dias seguidos indica que entrou mais dinheiro do que saiu; saldo negativo, o inverso.</p>

<h3>Holders de curto e de longo prazo</h3>
<p>Inspirado em análises usadas no mercado de bitcoin, o painel separa os VELL pelo tempo que estão parados na mesma carteira. Os <b>holders de curto prazo</b> (Short-Term Holders, STH) seguram moedas compradas recentemente; os <b>holders de longo prazo</b> (Long-Term Holders, LTH) seguram moedas há mais tempo. Para cada grupo o painel calcula o <b>preço de custo médio</b>: quando o preço atual fica abaixo do custo dos holders de curto prazo, a maioria deles está no prejuízo, o que costuma aumentar a pressão de venda; acima, a maioria está no lucro.</p>

<h3>SOPR (resultado das vendas)</h3>
<p>O SOPR compara o preço de venda com o preço que o vendedor pagou. Acima de 1, quem vendeu naquele dia vendeu com lucro, em média; abaixo de 1, vendeu com prejuízo. Sequências abaixo de 1 indicam vendas por desistência ou medo.</p>

<h3>Leitura do mercado</h3>
<p>A leitura do mercado junta vários sinais (fluxo de compras e vendas, situação dos holders, liquidez, concentração) numa nota que vai de muito negativo a muito positivo. A seção “Por que deu essa leitura” mostra o peso de cada sinal, e o “Teste contra o passado” mostra como essa leitura teria se saído em datas anteriores. É uma ferramenta estatística simples, não uma previsão garantida.</p>

<h3>Concentração e maiores holders</h3>
<p>Mostra quantas carteiras existem em cada faixa de tamanho, quanto do total está nas maiores carteiras e quem está acumulando ou vendendo. Carteiras de contratos (como o pool e o próprio contrato do token) são identificadas para não distorcer a conta. O painel também agrupa carteiras ligadas entre si — por exemplo, que receberam VELL da mesma origem — para dar uma ideia mais realista de concentração.</p>

<h3>Queimas</h3>
<p>Queimar tokens é enviá-los para um endereço do qual ninguém consegue tirá-los, reduzindo a quantidade em circulação. O painel lista cada queima, soma por período e mostra quem mais queimou.</p>

<h3>Lucro ou prejuízo de uma carteira</h3>
<p>Digite um endereço da BSC e o painel calcula, com base no histórico público, quanto aquela carteira pagou pelos VELL, quanto recebeu nas vendas e qual o resultado atual. A consulta é feita no seu próprio navegador com os dados já publicados no site; o endereço digitado não é enviado nem guardado por nós.</p>

<h3>Comparação com outras criptomoedas</h3>
<p>Compara a variação do VELL com a do BNB e de outros tokens no mesmo período, para mostrar se o movimento foi do VELL ou do mercado como um todo.</p>

<h2>Limitações</h2>
<p>Os números dependem de como cada transação é interpretada. Transferências entre carteiras da mesma pessoa, negociações fora do pool principal e contratos desconhecidos podem fazer as estimativas de custo e de lucro se afastarem da realidade de alguém em particular. Use o painel como uma visão geral, não como extrato oficial.</p>
""", c)

    contato = (f'<p>Escreva para <a href="mailto:{html.escape(c["email"])}">{html.escape(c["email"])}</a>. Respondemos assim que possível.</p>'
               if c["email"] else "")
    pg["contato.html"] = _pagina("Contato", "Como falar com o responsável pelo Monitor Token VELL.", f"""
<h1>Contato</h1>
<p>Encontrou um erro nos números, tem uma sugestão de métrica ou quer falar sobre o site?</p>
{contato}
<p>Você também pode abrir um relato público no repositório do projeto: <a href="{REPO}/issues" rel="noopener">{REPO.replace("https://", "")}/issues</a>.</p>
<p class="mut">Não pedimos e nunca vamos pedir sua frase de recuperação (seed), chave privada ou senha. Desconfie de qualquer pessoa que diga falar em nome deste site pedindo esses dados.</p>
""", c)

    pg["privacidade.html"] = _pagina("Política de Privacidade", "Quais dados o Monitor Token VELL usa, cookies e anúncios do Google.", f"""
<h1>Política de Privacidade</h1>
<p class="mut">Atualizada em {hoje}.</p>
<p>Esta política explica como o Monitor Token VELL (“o site”), disponível em {c["url"]}, trata informações dos visitantes, em conformidade com a Lei Geral de Proteção de Dados (Lei 13.709/2018 – LGPD).</p>

<h2>1. Dados que exibimos</h2>
<p>O painel mostra apenas dados públicos da blockchain BNB Smart Chain (endereços de carteiras, valores e datas de transações). Esses registros são públicos por natureza e não identificam, por si sós, quem é o dono de cada carteira.</p>

<h2>2. Dados que coletamos de você</h2>
<p>Não temos cadastro, login nem formulários. Não coletamos nome, e-mail, CPF ou dados de pagamento. Quando você consulta uma carteira, o cálculo é feito no seu navegador; o endereço digitado não é enviado nem guardado por nós.</p>
<p>O site é hospedado no GitHub Pages, que pode registrar dados técnicos de acesso (como endereço IP e navegador) para segurança e funcionamento do serviço, conforme a <a href="https://docs.github.com/pt/site-policy/privacy-policies/github-general-privacy-statement" rel="noopener">política de privacidade do GitHub</a>.</p>

<h2>3. Armazenamento local e cookies</h2>
<p>Usamos o armazenamento local do navegador (localStorage) só para lembrar suas preferências, como a aba aberta, o tipo de gráfico e se você já viu o aviso de cookies. Você pode apagar esses dados nas configurações do navegador a qualquer momento.</p>

<h2>4. Anúncios do Google (AdSense)</h2>
<p>Este site pode exibir anúncios fornecidos pelo Google AdSense. Sobre isso:</p>
<ul>
<li>Fornecedores terceiros, incluindo o Google, usam cookies para veicular anúncios com base em visitas anteriores do usuário a este e a outros sites.</li>
<li>Com o uso de cookies de publicidade, o Google e os parceiros dele podem veicular anúncios para você com base nas suas visitas a este e/ou a outros sites na Internet.</li>
<li>Você pode desativar a publicidade personalizada nas <a href="https://adssettings.google.com" rel="noopener">Configurações de anúncios do Google</a> (Minha Central de Anúncios). Também é possível desativar cookies de fornecedores terceiros em <a href="https://www.aboutads.info/choices" rel="noopener">www.aboutads.info/choices</a>.</li>
<li>Saiba como o Google usa os dados dos sites parceiros em <a href="https://policies.google.com/technologies/partner-sites" rel="noopener">policies.google.com/technologies/partner-sites</a>.</li>
</ul>
<p>Visitantes do Espaço Econômico Europeu, do Reino Unido e da Suíça veem uma mensagem de consentimento gerenciada pelo Google antes de qualquer anúncio personalizado.</p>

<h2>5. Serviços de terceiros</h2>
<p>O site carrega bibliotecas de gráficos do cdnjs (Cloudflare). Links para lojas de aplicativos e exploradores de blocos levam a sites de terceiros, com políticas próprias.</p>

<h2>6. Seus direitos</h2>
<p>Pela LGPD você pode pedir informações sobre o tratamento de dados, correção ou eliminação. Como não guardamos dados pessoais dos visitantes, na maioria dos casos não há o que corrigir ou apagar do nosso lado; para dados tratados pelo Google ou pelo GitHub, use os canais desses serviços. Fale conosco pela página de <a href="contato.html">contato</a>.</p>

<h2>7. Mudanças</h2>
<p>Esta política pode ser atualizada. A data no topo indica a versão em vigor.</p>
""", c)

    pg["termos.html"] = _pagina("Termos de uso", "Condições de uso do Monitor Token VELL e aviso de risco.", f"""
<h1>Termos de uso</h1>
<p class="mut">Atualizados em {hoje}.</p>
<p>Ao usar o Monitor Token VELL você concorda com estes termos.</p>
<h2>1. Finalidade informativa</h2>
<p>O site reúne e organiza dados públicos da blockchain para fins informativos e educativos. <b>Nenhum conteúdo do site é recomendação de investimento, oferta de compra ou venda de ativos ou consultoria financeira</b>, nem foi elaborado por analista de valores mobiliários credenciado.</p>
<h2>2. Risco</h2>
<p>Criptomoedas e tokens são investimentos de altíssimo risco, com variações bruscas de preço e possibilidade de perda total. Faça sua própria pesquisa e, se necessário, procure um profissional habilitado antes de investir.</p>
<h2>3. Precisão dos dados</h2>
<p>Os números são calculados automaticamente e podem conter atrasos, erros ou interpretações imprecisas de transações. O site é oferecido “no estado em que se encontra”, sem garantia de exatidão, completude ou disponibilidade contínua.</p>
<h2>4. Responsabilidade</h2>
<p>O responsável pelo site não responde por perdas ou danos decorrentes de decisões tomadas com base nas informações aqui exibidas.</p>
<h2>5. Links e indicações</h2>
<p>O site pode conter links para aplicativos, exploradores de blocos e outros sites, inclusive com código de indicação. Não controlamos esses serviços nem respondemos por eles.</p>
<h2>6. Anúncios</h2>
<p>O site pode exibir anúncios de terceiros. A exibição de um anúncio não significa que recomendamos o produto anunciado.</p>
<h2>7. Alterações</h2>
<p>Estes termos podem mudar a qualquer momento; a data no topo indica a versão em vigor.</p>
""", c)

    paginas_mapa = ["", "sobre.html", "privacidade.html", "termos.html", "contato.html"]
    hoje_iso = time.strftime("%Y-%m-%d")
    pg["sitemap.xml"] = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                         + "".join(f"  <url><loc>{c['url']}/{p}</loc><lastmod>{hoje_iso}</lastmod></url>\n" for p in paginas_mapa)
                         + "</urlset>\n")
    pg["robots.txt"] = f"User-agent: *\nAllow: /\n\nSitemap: {c['url']}/sitemap.xml\n"
    if c["adsense"]:
        pg["ads.txt"] = f"google.com, {c['adsense'].replace('ca-', '', 1)}, DIRECT, f08c47fec0942fa0\n"
    return pg
