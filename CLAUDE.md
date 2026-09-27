# Contexto do projeto (para o Claude Code)

Este projeto nasceu de uma sessão em que consolidamos, para a contabilidade, as
finanças de **Iuri Henrique Teixeira Gonçalves (PF)** e do **Youup Instituto
Avançado de Saúde (PJ, CNPJ 55.214.289/0001-33)**, referente a **jan–ago/2026**.

O objetivo: transformar um monte de faturas e extratos em **uma planilha
categorizada**, sem contar o mesmo gasto duas vezes. O código aqui é a versão
"produtizada" desse processo manual.

## Como o pipeline funciona

`contabil/pipeline.py` → `process(paths)`:
1. **Deduplica** arquivos por hash (evita PDFs repetidos, ex.: PagBank enviado 2x).
2. **Detecta a origem** de cada arquivo pelo *conteúdo* (`detect_source`), não pelo nome.
3. **Faz o parsing** por origem em lançamentos normalizados (um dict por linha).
4. **Reconciliação** (`reconcile` + trecho no `process`): reclassifica pagamentos
   de fatura para não duplicar.

`contabil/build.py` → `build_workbook(tx, out)`: monta o Excel (Leia-me, Resumo,
PF, PJ, Listas) com fórmulas SUMIFS, menu suspenso de categorias e Resumo que
espelha a aba Listas.

## Regras de negócio que NÃO podem se perder

- **PF x PJ é pela titularidade da conta**, não pela natureza do gasto.
  Conta/cartão do Iuri = PF; conta/cartão da Youup = PJ. A classificação fiscal
  final é do contador.
- **Dupla contagem — a regra mais importante.** As despesas reais vêm das
  **compras** detalhadas nas faturas dos cartões. O **pagamento da fatura** que
  aparece nos extratos bancários NÃO é despesa (é quitação) e é marcado como
  `tipo = "Pagamento de fatura de cartão"` (memo, fora dos totais). Isso vale para
  Itaú, BTG, Caixa, Mercado Pago e Cora.
  - Nos extratos, reclassificamos: `"cartões caixa"` → memo; `"mercado pago
    instituição"` cujo valor casa com o total de uma fatura MP → memo;
    `"pagamento da fatura Cora"` → memo (quando a fatura Cora itemizada está presente).
- **PagBank/Moderninha**: cada venda gera pernas internas ("Pagamento liberado",
  "Liberação de saldo"). Só **"Venda pela Moderninha"** conta como receita e as
  **"Taxas"** como despesa; as pernas de liquidação são `Liquidação/Interno` (memo).
- **Cartão BTG (.xlsx) — ano das datas.** O arquivo traz só dia+mês. A fatura de
  um mês cobra compras do mês anterior; então **se o mês da compra > mês da
  fatura, o ano é o anterior** (ver `parse_btg_card`). Sem isso, compras de
  nov/dez viram "2026" (futuro).
- **Cartão Cora (PJ)** está no **rotativo**: o "valor a pagar" da fatura ≠ "total
  de compras". A despesa real é o **Total de compras** (itemizado na seção
  "Lançamentos DD/MM a DD/MM"), e os períodos das faturas não se sobrepõem.
- **Transferências entre contas do mesmo titular** (Iuri↔Iuri) = memo
  (`Transferência entre contas próprias`). Transferências **PF↔PJ (Youup)** ficam
  numa categoria própria e visível (não são netadas).

## Categorias

`CAT_RULES` em `pipeline.py` é uma lista de `(categoria, [palavras-chave])`,
avaliada em ordem. `categorizar()` devolve a 1ª que casar, senão `"A classificar"`.
São **sugestões** — o usuário revisa. A aba **Listas** alimenta um menu suspenso;
categorias novas digitadas lá aparecem no dropdown e ganham linha no Resumo
(que espelha `Listas!A2:A100`).

## Como estender

**Adicionar uma nova fonte** (ex.: outro banco):
1. Escreva `parse_<fonte>(texto_ou_path)` em `pipeline.py`, devolvendo dicts via `_tx(...)`.
2. Adicione um marcador forte em `detect_source` (cabeçalho único do documento).
3. Ligue no dispatch dentro de `process()`.
4. Rode o teste (`python -m contabil.cli <pasta> saida.xlsx`) e confira a
   reconciliação por fonte impressa.

**Regra de ouro ao mexer:** um marcador de detecção tem que ser **único do
cabeçalho** do documento, porque extratos contêm transações que mencionam outros
bancos/cartões (foi assim que extratos viravam "cartão Caixa" por engano).

## Quirks conhecidos / a melhorar

- Datas em 2025 (compras de fim de 2025 cobradas em faturas de 2026) ficam fora
  do intervalo 2026 na aba "Movimentação por mês" — é esperado (a data é a data
  real da compra). Alternativa: datar pelo mês da fatura.
- Faturas Cora só cobrem a partir de 24/02/2026; compras de jan/início de fev
  desse cartão exigiriam faturas anteriores.
- O ano-base está fixo em `ANO_PADRAO = 2026` em `pipeline.py`.
- `OWN` (nomes do titular para detectar transferência própria) está hardcoded.

## Camada de visualização e previsão (adicionada)

O consolidador (`pipeline`+`build`) segue intacto e continua alimentando a
contabilidade. Em cima dele há duas peças novas e um app em abas:

- **`contabil/store.py`** — histórico em SQLite local (`data/historico.db`).
  - `save_transactions` deduplica por conteúdo: o id de cada lançamento é um
    hash determinístico dos campos + índice de ocorrência no lote, então
    reimportar os mesmos arquivos NÃO conta duas vezes (e duplicatas legítimas
    do mesmo dia/valor são preservadas).
  - `categoria_manual` guarda reclassificações do usuário; a categoria efetiva
    é a manual, se houver (o `categoria_auto` original é mantido).
  - `recurring_overrides` e `settings` guardam os ajustes de previsão.
- **`contabil/forecast.py`** — detecção de fixos/recorrentes e projeção.
  - `merchant_key` reduz a descrição a um "comerciante" estável (sem números/
    ruído) para agrupar gastos repetidos.
  - `detect_recurring`: grupos que aparecem em ≥ `min_meses` são recorrentes;
    baixa variação ⇒ "fixo", senão "recorrente". Valor sugerido = mediana.
  - `effective_recurring`: funde o detectado com os overrides do usuário
    (valor/categoria/ativo) e itens manuais.
  - `project`: mês futuro = Σ(recorrentes ativos) + baseline variável×(1+g)^k.
    **Anti-dupla-contagem:** o baseline variável é a média recente de
    (despesa do mês − despesa recorrente do mês), então o que já está nos
    recorrentes não entra de novo.
- **`app.py`** — 3 abas: Importar (consolida+salva+xlsx), Dashboard (Plotly
  sobre o histórico), Previsão (recorrentes editáveis + projeção).

**Quirk:** desativar um recorrente joga o histórico dele para o baseline
variável (comportamento intencional). A projeção fixa o valor do recorrente na
mediana; para capturar tendência de um item específico, edite o valor na aba
Previsão.

## Estrutura

```
app.py                 # interface Streamlit (3 abas)
contabil/
  pipeline.py          # helpers, categorização, detecção, parsers, process()
  build.py             # monta o Excel
  cli.py               # uso por linha de comando
  store.py             # histórico SQLite (dedup, overrides de categoria/recorrentes)
  forecast.py          # detecção de fixos/recorrentes + projeção
data/                  # historico.db (SQLite, não versionado)
requirements.txt
README.md
CLAUDE.md              # este arquivo
```
