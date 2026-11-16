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
| `gerar_site.py` | Gera a versão online (usado pelo GitHub). |
| `.gitignore` | O que não vai para o GitHub (banco de dados, temporários, segredos). |

## De onde vêm os dados

- Eventos do token e do pool: servidores públicos da BSC (NodeReal e PublicNode).
- Preço do BNB em dólar: Binance.

O endereço do NodeReal em `vellcfg.py` usa uma chave pública compartilhada. Se o programa
começar a falhar ao atualizar, crie uma chave gratuita em https://nodereal.io e troque no arquivo.

## Versão online (GitHub Pages)

O painel online fica em **https://israelramires.github.io/vell-monitor/** e se atualiza
sozinho, sem servidor pago:

- A cada ~10 minutos o GitHub roda o arquivo `.github/workflows/atualizar-painel.yml`.
- Ele recupera o banco da vez anterior, busca os eventos novos da BSC (`gerar_site.py`),
  recalcula tudo e publica o painel no GitHub Pages.
- O banco fica guardado no próprio GitHub (cache do Actions). Se um dia sumir, ele parte
  da cópia anexada na versão "banco-inicial" do repositório e completa pela blockchain.

Diferenças em relação ao programa no PC: o online atualiza a cada ~10 minutos (o GitHub
às vezes atrasa alguns minutos), e o PC a cada 2.

### Para corrigir ou mudar algo

1. Altere aqui no PC e teste em http://localhost:8765 (dê dois cliques em `iniciar.bat`).
2. Salve a versão no git e envie ao GitHub (`git push`).
3. O envio dispara a atualização: em 2 a 4 minutos o site já está com a mudança.
4. Para desfazer, volte a versão no git e envie de novo.

Para acompanhar ou forçar uma atualização: aba **Actions** do repositório no GitHub,
"Atualizar painel online" → "Run workflow".

Observação: o GitHub desliga tarefas agendadas de repositórios sem nenhuma alteração por
60 dias. Se o site parar de atualizar, basta enviar qualquer mudança ou clicar em
"Enable workflow" na aba Actions.

### Rodar em outro servidor (opcional)

`Dockerfile`, `Procfile`, `requirements.txt` e `.env.example` permitem rodar o programa
completo (com atualização a cada 2 minutos) em serviços como Railway, Render ou uma VPS,
com um disco permanente montado em `/data`.

## Limites conhecidos

- Só enxerga negociações no pool VELL/WBNB da PancakeSwap v2.
- "Grupos de carteiras ligadas" usa só transferências diretas de VELL entre carteiras;
  não vê quem mandou BNB para quem.
- Lucro e preço de custo são estimativas pelo método do custo médio. Tokens recebidos por
  transferência entram com custo zero.
