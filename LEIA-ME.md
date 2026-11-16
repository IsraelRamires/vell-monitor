# MONITOR TOKEN VELL

Programa que junta os dados públicos da blockchain (rede BSC) sobre o token VELL
e mostra tudo num painel no navegador.

## Como usar

1. Dê dois cliques em **iniciar.bat**.
2. O painel abre sozinho em http://localhost:8765 .
3. Deixe a janela preta aberta enquanto quiser acompanhar. Para parar, feche a janela.

Enquanto estiver aberto, o programa busca dados novos a cada 2 minutos.
Ao abrir de novo, ele baixa sozinho tudo o que aconteceu enquanto esteve fechado.

Precisa do Python 3.9 ou mais novo instalado (não precisa instalar mais nada) e de internet.

## O que o painel mostra

- **Visão geral** — preço, variações, valor de mercado, liquidez, holders, destaques automáticos.
- **Volume** — por dia, semana, mês e ano; compras x vendas; saldo líquido; dias e horas mais ativos.
- **Baleias e carteiras** — concentração, maiores holders, quem acumula e quem vende,
  preço de custo e lucro de cada carteira, distribuição inicial feita pelo dono do contrato,
  grupos de carteiras ligadas entre si.
- **Compras e vendas** — cada negociação, com a carteira, o valor e a taxa cobrada pelo contrato.
- **Liquidez e contrato** — tamanho do pool, quem é dono da liquidez, entradas e saídas,
  impacto no preço por tamanho de ordem, dono do contrato.
- **VELL x BNB** — quanto o VELL acompanha o BNB e qual é o movimento próprio dele.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `iniciar.bat` | Abre o programa. |
| `vellcfg.py` | Configurações (intervalo de atualização, porta, limites de baleia). |
| `coletor.py` | Baixa os eventos da blockchain para `dados/vell.db`. |
| `metricas.py` | Calcula as métricas. |
| `servidor.py` | Atualiza os dados e serve o painel. |
| `painel.html` | A página do painel. |
| `.gitignore` | O que não vai para o GitHub (banco de dados, temporários, segredos). |

## De onde vêm os dados

- Eventos do token e do pool: servidores públicos da BSC (NodeReal e PublicNode).
- Preço do BNB em dólar: Binance.

O endereço do NodeReal em `vellcfg.py` usa uma chave pública compartilhada. Se o programa
começar a falhar ao atualizar, crie uma chave gratuita em https://nodereal.io e troque no arquivo.

## Versão online

O mesmo programa roda num servidor. Ele precisa ficar ligado o tempo todo e ter um
**disco permanente** para o banco (`vell.db`), então hospedagem de site simples não serve.
Opções: Railway ou Render (atualizam sozinhos a partir do GitHub) ou uma VPS com Docker.

Arquivos usados online:

| Arquivo | Para que serve |
|---|---|
| `Dockerfile` | Receita para montar o servidor (Python 3.11, sem pacotes extras). |
| `Procfile`, `requirements.txt`, `.python-version` | Para serviços que rodam Python direto, sem Docker. |
| `.env.example` | Lista das configurações online (copie e preencha no painel do serviço). |

Passos:

1. Envie esta pasta para um repositório **privado** no GitHub.
2. No serviço de hospedagem, crie o projeto a partir desse repositório (ele usa o `Dockerfile`).
3. Crie um disco permanente montado em `/data`.
4. Cadastre as variáveis de `.env.example`, principalmente `VELL_RPC_ARCHIVE` com a sua
   chave grátis do NodeReal.
5. Na primeira vez o servidor baixa todo o histórico da blockchain (alguns minutos).
   Depois só busca o que for novo, a cada 2 minutos.

Para corrigir ou mudar algo: altere aqui no PC, teste em http://localhost:8765, salve
a versão no git e envie ao GitHub. O serviço percebe e reinicia sozinho com a versão nova.
Se der problema, volte para a versão anterior pelo próprio serviço ou pelo git.

Para conferir se o servidor está vivo: `/api/status`.

## Limites conhecidos

- Só enxerga negociações no pool VELL/WBNB da PancakeSwap v2.
- "Grupos de carteiras ligadas" usa só transferências diretas de VELL entre carteiras;
  não vê quem mandou BNB para quem.
- Lucro e preço de custo são estimativas pelo método do custo médio. Tokens recebidos por
  transferência entram com custo zero.
