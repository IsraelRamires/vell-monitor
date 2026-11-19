"""Configuração do monitor do VELL. Altere aqui se precisar.

Na versão online, alguns valores vêm de variáveis de ambiente (veja .env.example):
VELL_RPC_ARCHIVE, VELL_HOST, PORT e VELL_DB. Sem elas, vale o que está escrito aqui.
"""
import os

# --- Token e par monitorados -------------------------------------------------
TOKEN = "0x40f4100b47189c4b41b5ae3d3156d304b3f753f2"   # VELL (VELLORA)
PAIR = "0xdbd63d58db817b3483f7e0f80e7239590e0ee115"    # VELL/WBNB PancakeSwap v2
SYMBOL = "VELL"
DECIMALS = 18
CREATION_BLOCK = 100_796_654        # bloco em que o contrato foi criado (27/05/2026)
LAUNCH_TS = 1791331200              # 07/10/2026 00:00 UTC — início das negociações

# --- Fontes de dados ---------------------------------------------------------
# Servidores públicos da BSC. O primeiro tem o histórico completo (arquivo);
# os outros servem só para as atualizações recentes, caso o primeiro falhe.
# Se quiser mais estabilidade, crie uma chave gratuita em https://nodereal.io
# e troque a parte final do primeiro endereço pela sua chave.
RPC_ARCHIVE = os.environ.get("VELL_RPC_ARCHIVE") or "https://bsc-mainnet.nodereal.io/v1/64a9df0874fb4a93b9d0a3849de012d3"
RPC_RECENT = ["https://bsc-rpc.publicnode.com"]
MAX_RANGE = 49_000                  # máximo de blocos por consulta de eventos

# --- Programa ----------------------------------------------------------------
UPDATE_SECONDS = 120                # intervalo entre atualizações (2 minutos)
PORT = int(os.environ.get("PORT") or 8765)          # endereço do painel: http://localhost:8765
# 127.0.0.1 = só este computador acessa. Online use 0.0.0.0 (aceita acessos de fora).
HOST = os.environ.get("VELL_HOST") or "127.0.0.1"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("VELL_DB") or os.path.join(BASE_DIR, "dados", "vell.db")
TZ_OFFSET_HOURS = -3                # horário de Brasília (para mostrar datas e horas)
# Fechamento de cada dia (volume por dia, "hoje", candles diários): 00:00 UTC = 21:00 de Brasília,
# o mesmo horário do candle diário do DexScreener e da Binance.
FECHAMENTO_DIA_UTC = 0

# Faixas de tamanho de carteira (em % do fornecimento total)
WHALE_PCT = 1.0                     # baleia: 1% ou mais do supply
SHARK_PCT = 0.1                     # tubarão: de 0,1% a 1%
BIG_TRADE_TOK = 100_000             # compra ou venda "grande" a partir desta quantidade de tokens
LIQ_EVENTO_USD = 500                # entrada/saída de liquidez que vira destaque a partir deste valor em USD

# --- Indicação da carteira Vellora (botão "Baixar carteira" do painel) ------
REF_CODIGO = "9A801622"             # seu código de indicação
REF_ANDROID = "https://play.google.com/store/apps/details?id=com.appvellora.vellora"
REF_IOS = "https://apps.apple.com/br/app/vellora-crypto-wallet/id6760142552"
