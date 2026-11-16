"""Configuração do monitor do VELL. Altere aqui se precisar."""
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
RPC_ARCHIVE = "https://bsc-mainnet.nodereal.io/v1/64a9df0874fb4a93b9d0a3849de012d3"
RPC_RECENT = ["https://bsc-rpc.publicnode.com"]
MAX_RANGE = 49_000                  # máximo de blocos por consulta de eventos

# --- Programa ----------------------------------------------------------------
UPDATE_SECONDS = 120                # intervalo entre atualizações (2 minutos)
PORT = 8765                         # endereço do painel: http://localhost:8765
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dados", "vell.db")
TZ_OFFSET_HOURS = -3                # horário de Brasília

# Faixas de tamanho de carteira (em % do fornecimento total)
WHALE_PCT = 1.0                     # baleia: 1% ou mais do supply
SHARK_PCT = 0.1                     # tubarão: de 0,1% a 1%
BIG_TRADE_USD = 500                 # negociação "grande" a partir deste valor em USD

# --- Indicação da carteira Vellora (botão "Baixar carteira" do painel) ------
REF_CODIGO = "9A801622"             # seu código de indicação
REF_ANDROID = "https://play.google.com/store/apps/details?id=com.appvellora.vellora"
REF_IOS = "https://apps.apple.com/br/app/vellora-crypto-wallet/id6760142552"
