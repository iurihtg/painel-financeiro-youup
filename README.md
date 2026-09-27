# Contabilidade & Previsão — Iuri / Youup

App que lê faturas de cartão e extratos bancários (PDF/Excel), normaliza os
lançamentos, evita dupla contagem e gera uma planilha (.xlsx) pronta para a
contabilidade, com abas **PF**, **PJ**, **Resumo** e **Listas** — e agora
também **acumula o histórico**, **visualiza** os gastos e **projeta** os
próximos meses.

O app tem 3 abas:

1. **📥 Importar** — sobe faturas/extratos, consolida, salva no histórico
   (banco local) e baixa a planilha `.xlsx`.
2. **📈 Dashboard** — sobre todo o histórico acumulado: KPIs (receita, despesa,
   resultado), receita×despesa por mês, resultado mensal, despesas por
   categoria, PF×PJ, maiores comerciantes e revisão de categorias
   ("A classificar") que fica gravada.
3. **🔮 Previsão** — detecta gastos **fixos/recorrentes** (tudo editável:
   ligar/desligar, mudar valor/categoria, adicionar item manual) e projeta os
   próximos meses = recorrentes ativos + baseline dos gastos variáveis, com
   crescimento % ajustável. Evita dupla contagem subtraindo o recorrente do
   baseline variável.

O histórico fica num SQLite local em `data/historico.db` (não versionado —
veja `.gitignore`). Reimportar os mesmos arquivos **não** conta duas vezes.

## Formatos de importação aceitos

| Formato | Como conseguir | Observação |
|---|---|---|
| **OFX** (recomendado) | Internet Banking (navegador) → exportar extrato | Padrão de qualquer banco; 1 arquivo do mês inteiro |
| **PDF** | Faturas/extratos Itaú, BTG, Caixa, Mercado Pago, Cora, PagBank | Leitores dedicados aos cartões do Iuri |
| **Excel (.xlsx)** | Faturas Itaú/BTG, ou a **planilha-modelo** (Data/Descrição/Valor) | O modelo é baixável na aba Importar |

Tudo cai no histórico como lançamentos; categorias em "A classificar" você revisa
no Dashboard. Deduplicação automática por conteúdo.

## Rodar na nuvem (Supabase) — opcional

Por padrão o app usa um SQLite local. Para acumular o histórico na nuvem
(acessível de qualquer lugar), use o **Supabase**:

1. Crie um projeto em supabase.com.
2. No **SQL Editor**, rode o arquivo `supabase_schema.sql` (cria as tabelas).
3. Defina as variáveis de ambiente antes de rodar o app:
   ```bash
   export SUPABASE_URL="https://SEU-PROJETO.supabase.co"
   export SUPABASE_KEY="SUA_SERVICE_ROLE_KEY"   # só no servidor; nunca no front-end
   ```
4. Rode normalmente (`streamlit run app.py`). A barra lateral mostra
   *Backend: Supabase (nuvem)*. Sem as variáveis, volta ao SQLite local.

> A `service_role key` tem acesso total ao banco — mantenha-a só no ambiente do
> servidor (variável de ambiente), nunca commitada nem no navegador.

## Instalação (uma vez)

Você precisa de Python 3.10+ instalado.

```bash
# 1. entrar na pasta do projeto
cd contabil-youup

# 2. criar um ambiente isolado
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. instalar as dependências
pip install -r requirements.txt
```

**Opcional (recomendado):** instale o `poppler`, que melhora a leitura dos PDFs.
Sem ele, o app usa o `pdfplumber` (já incluído) como alternativa.
- macOS: `brew install poppler`
- Ubuntu/Debian: `sudo apt install poppler-utils`
- Windows: baixe o poppler e adicione a pasta `bin` ao PATH.

## Como usar

```bash
source .venv/bin/activate        # se ainda não estiver ativo
streamlit run app.py
```

Abre no navegador. Arraste **todas** as faturas e extratos, clique em
**Processar** e baixe a planilha. Arquivos repetidos são ignorados sozinhos.

## Uso pela linha de comando (sem interface)

```bash
python -m contabil.cli pasta_com_os_arquivos/ saida.xlsx
```

## O que ele reconhece

| Fonte | Formato | Escopo |
|---|---|---|
| Cartão Itaú 6434 / 4482 | .xlsx | PF |
| Cartão BTG | .xlsx | PF |
| Cartão Caixa 1016 | PDF | PF |
| Cartão Mercado Pago 1347 | PDF | PF |
| Cartão Cora (Youup) | PDF | PJ |
| Conta BTG / Itaú | PDF | PF |
| Conta Cora (Youup) | PDF | PJ |
| PagBank / Moderninha | PDF | PJ |

Detalhes da lógica (regras de categoria, dupla contagem, datas) estão em
**CLAUDE.md** — leia esse arquivo antes de mexer no código.
