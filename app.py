# -*- coding: utf-8 -*-
"""
Interface web (Streamlit): consolidar → visualizar → prever.

Abas:
  1. Importar  — sobe faturas/extratos, consolida, salva no histórico e baixa o .xlsx
  2. Dashboard — gráficos de gastos/receitas sobre TODO o histórico acumulado
  3. Previsão  — detecta fixos/recorrentes (editáveis) e projeta os próximos meses

Rodar:  streamlit run app.py
"""
import os
import tempfile
import datetime as dt

import pandas as pd
import plotly.express as px
import streamlit as st

from contabil.pipeline import process, modelo_excel_bytes
from contabil.build import build_workbook
from contabil import db
from contabil import forecast as fc

st.set_page_config(page_title="Contabilidade & Previsão — Iuri/Youup", page_icon="📊", layout="wide")


def _secret(chave, default=None):
    """Lê de variável de ambiente (local) ou dos Secrets do Streamlit Cloud."""
    if os.environ.get(chave):
        return os.environ[chave]
    try:
        return st.secrets[chave]
    except Exception:
        return default


# Hospedado: joga os segredos do Streamlit Cloud no ambiente para o backend achar
for _k in ("SUPABASE_URL", "SUPABASE_KEY"):
    _v = _secret(_k)
    if _v and not os.environ.get(_k):
        os.environ[_k] = str(_v)

# Trava por senha (opcional): defina APP_SENHA nos Secrets para proteger o link
_SENHA = _secret("APP_SENHA")
if _SENHA and not st.session_state.get("_ok"):
    st.title("🔒 Painel Financeiro")
    _tent = st.text_input("Senha de acesso", type="password")
    if _tent == _SENHA:
        st.session_state["_ok"] = True
        st.rerun()
    elif _tent:
        st.error("Senha incorreta.")
    st.stop()

store = db.active()  # SQLite local ou Supabase (nuvem), conforme o ambiente

PALETA = px.colors.qualitative.Safe
VERDE, VERMELHO = "#2E7D32", "#C0392B"


def brl(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"


def carregar_df(escopo=None):
    """Carrega o histórico do banco como DataFrame já com colunas úteis."""
    tx = store.load_transactions(escopo=escopo)
    if not tx:
        return pd.DataFrame(), tx
    df = pd.DataFrame(tx)
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df["mes"] = df["data"].dt.strftime("%Y-%m")
    df["comerciante"] = df["descricao"].map(fc._label)
    for c in ("entrada", "saida"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df, tx


st.title("📊 Contabilidade & Previsão de Gastos")
st.caption("Consolida faturas/extratos, acumula o histórico e mostra onde você gasta, "
           "lucra e para onde as despesas estão indo.")

try:
    n_hist = store.count_transactions()
except Exception as e:
    n_hist = 0
    st.sidebar.error(f"Banco indisponível: {e}")
st.sidebar.metric("Lançamentos no histórico", f"{n_hist:,}".replace(",", "."))
st.sidebar.caption(f"Backend: {db.backend_nome()}")

tab_imp, tab_dash, tab_prev = st.tabs(["📥 Importar", "📈 Dashboard", "🔮 Previsão"])

# ══════════════════════════════ 1. IMPORTAR ══════════════════════════════
with tab_imp:
    with st.expander("O que subir aqui"):
        st.markdown(
            "- **OFX (recomendado)**: extrato do mês inteiro exportado no Internet Banking "
            "de qualquer banco. Mais confiável e sem depender do formato do PDF.\n"
            "- **Cartões**: faturas Itaú (6434/4482, .xlsx), BTG (.xlsx), Caixa (PDF), "
            "Mercado Pago (PDF), Cora/Youup (PDF)\n"
            "- **Contas**: extratos BTG, Itaú e Cora (PDF)\n"
            "- **Adquirência**: extrato PagBank/Moderninha (PDF)\n"
            "- **Planilha-modelo (.xlsx)**: plano B universal — colunas Data / Descrição / Valor.\n\n"
            "Pode subir tudo de uma vez. Arquivos repetidos são ignorados automaticamente."
        )
        st.download_button("⬇️ Baixar planilha-modelo (Data/Descrição/Valor)",
                           data=modelo_excel_bytes(), file_name="modelo_lancamentos.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    files = st.file_uploader("Arquivos", type=["ofx", "pdf", "xlsx", "xlsm"],
                             accept_multiple_files=True)

    if st.button("Processar", type="primary", disabled=not files):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for f in files:
                p = os.path.join(tmp, f.name)
                with open(p, "wb") as out:
                    out.write(f.getbuffer())
                paths.append(p)
            with st.spinner("Processando…"):
                tx, rep = process(paths)
                out_xlsx = os.path.join(tmp, f"Despesas_{dt.date.today().isoformat()}.xlsx")
                build_workbook(tx, out_xlsx)
                with open(out_xlsx, "rb") as fh:
                    data = fh.read()
            st.session_state["tx_proc"] = tx
            st.session_state["xlsx"] = data
            st.session_state["xlsx_name"] = os.path.basename(out_xlsx)
            st.session_state["rep"] = rep

    if "tx_proc" in st.session_state:
        tx = st.session_state["tx_proc"]
        rep = st.session_state["rep"]
        st.success(f"{rep['total']} lançamentos consolidados neste lote.")

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Arquivos lidos")
            st.dataframe(pd.DataFrame(rep["arquivos"]), use_container_width=True, hide_index=True)
            if rep["ignorados"]:
                st.warning("Não reconhecidos: " + ", ".join(rep["ignorados"]))
        with c2:
            st.subheader("Totais por fonte")
            st.dataframe(pd.DataFrame(rep["por_fonte"]), use_container_width=True, hide_index=True)

        b1, b2 = st.columns([1, 1])
        with b1:
            if st.button("💾 Salvar no histórico", type="primary"):
                ins, ign = store.save_transactions(tx)
                st.success(f"{ins} novos lançamentos salvos. {ign} já existiam (ignorados).")
        with b2:
            st.download_button("⬇️ Baixar planilha (.xlsx)", data=st.session_state["xlsx"],
                               file_name=st.session_state["xlsx_name"],
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.subheader("Prévia dos lançamentos")
        df = pd.DataFrame(tx)
        if not df.empty:
            df["data"] = df["data"].astype(str)
            st.dataframe(df[["data", "escopo", "fonte", "descricao", "categoria",
                             "tipo", "entrada", "saida"]], use_container_width=True, hide_index=True)

# ══════════════════════════════ 2. DASHBOARD ══════════════════════════════
with tab_dash:
    df_all, tx_all = carregar_df()
    if df_all.empty:
        st.info("Sem histórico ainda. Importe arquivos e clique em **Salvar no histórico** na aba Importar.")
    else:
        meses = fc.meses_disponiveis(tx_all)
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            escopo_sel = st.selectbox("Escopo", ["Todos", "PF (Iuri)", "PJ (Youup)"])
        with c2:
            m_ini = st.selectbox("Mês inicial", meses, index=0)
        with c3:
            m_fim = st.selectbox("Mês final", meses, index=len(meses) - 1)

        df = df_all[(df_all["mes"] >= m_ini) & (df_all["mes"] <= m_fim)].copy()
        if escopo_sel.startswith("PF"):
            df = df[df["escopo"] == "PF"]
        elif escopo_sel.startswith("PJ"):
            df = df[df["escopo"] == "PJ"]

        desp = df[df["tipo"] == "Despesa"]
        rec = df[df["tipo"] == "Receita"]
        total_desp = desp["saida"].sum()
        total_rec = rec["entrada"].sum()
        resultado = total_rec - total_desp

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Receitas", brl(total_rec))
        k2.metric("Despesas", brl(total_desp))
        k3.metric("Resultado", brl(resultado), delta=f"{'lucro' if resultado >= 0 else 'prejuízo'}")
        k4.metric("Nº de lançamentos", f"{len(df):,}".replace(",", "."))

        st.divider()

        # evolução mensal: receita vs despesa
        g1, g2 = st.columns(2)
        # base mensal robusta: uma coluna Receita e uma Despesa por linha, depois soma
        mensal = df.assign(
            Receita=df["entrada"].where(df["tipo"] == "Receita", 0.0),
            Despesa=df["saida"].where(df["tipo"] == "Despesa", 0.0),
        ).groupby("mes")[["Receita", "Despesa"]].sum()
        with g1:
            st.subheader("Receita × Despesa por mês")
            piv = mensal.reset_index().melt("mes", var_name="Tipo", value_name="Valor")
            fig = px.bar(piv, x="mes", y="Valor", color="Tipo", barmode="group",
                         color_discrete_map={"Receita": VERDE, "Despesa": VERMELHO})
            fig.update_layout(xaxis_title="", yaxis_title="", legend_title="", height=360)
            st.plotly_chart(fig, use_container_width=True)
        with g2:
            st.subheader("Resultado mensal (receita − despesa)")
            res = (mensal["Receita"] - mensal["Despesa"]).reset_index(name="Resultado")
            fig = px.bar(res, x="mes", y="Resultado",
                         color=res["Resultado"] >= 0,
                         color_discrete_map={True: VERDE, False: VERMELHO})
            fig.update_layout(xaxis_title="", yaxis_title="", showlegend=False, height=360)
            st.plotly_chart(fig, use_container_width=True)

        # despesas por categoria + PF/PJ
        g3, g4 = st.columns([2, 1])
        with g3:
            st.subheader("Onde vai o dinheiro — despesas por categoria")
            cat = desp.groupby("categoria")["saida"].sum().sort_values(ascending=True).reset_index()
            cat = cat[cat["saida"] > 0].tail(15)
            fig = px.bar(cat, x="saida", y="categoria", orientation="h",
                         color="saida", color_continuous_scale="Reds")
            fig.update_layout(xaxis_title="", yaxis_title="", coloraxis_showscale=False,
                              height=max(360, 24 * len(cat)))
            st.plotly_chart(fig, use_container_width=True)
        with g4:
            st.subheader("PF × PJ (despesas)")
            pfpj = desp.groupby("escopo")["saida"].sum().reset_index()
            if not pfpj.empty:
                fig = px.pie(pfpj, names="escopo", values="saida", hole=0.5,
                             color_discrete_sequence=PALETA)
                fig.update_layout(height=300, legend_title="")
                st.plotly_chart(fig, use_container_width=True)
            st.subheader("Maiores comerciantes")
            top = desp.groupby("comerciante")["saida"].sum().sort_values(ascending=False).head(10)
            st.dataframe(top.map(brl).reset_index().rename(columns={"saida": "Despesa"}),
                         use_container_width=True, hide_index=True)

        # reclassificação de "A classificar"
        st.divider()
        st.subheader("✍️ Revisar categorias")
        st.caption("Ajuste a categoria e salve — a mudança fica gravada no histórico.")
        so_classificar = st.checkbox("Mostrar só 'A classificar'", value=True)
        rev = df.copy()
        if so_classificar:
            rev = rev[rev["categoria"] == "A classificar"]
        if rev.empty:
            st.info("Nada pendente aqui. 🎉")
        else:
            cats = sorted(df_all["categoria"].dropna().unique().tolist())
            edit = rev[["id", "data", "fonte", "descricao", "categoria", "saida"]].copy()
            edit["data"] = edit["data"].dt.strftime("%d/%m/%Y")
            edited = st.data_editor(
                edit, use_container_width=True, hide_index=True, key="rev_editor",
                disabled=["id", "data", "fonte", "descricao", "saida"],
                column_config={
                    "id": None,
                    "categoria": st.column_config.SelectboxColumn("Categoria", options=cats),
                    "saida": st.column_config.NumberColumn("Saída", format="R$ %.2f"),
                })
            if st.button("💾 Salvar categorias"):
                orig = dict(zip(edit["id"], edit["categoria"]))
                n = 0
                for _, r in edited.iterrows():
                    if r["categoria"] != orig.get(r["id"]):
                        store.set_categoria_manual(r["id"], r["categoria"])
                        n += 1
                st.success(f"{n} categoria(s) atualizada(s).")
                st.rerun()

# ══════════════════════════════ 3. PREVISÃO ══════════════════════════════
with tab_prev:
    df_all, tx_all = carregar_df()
    if df_all.empty:
        st.info("Sem histórico ainda. Importe e salve lançamentos para projetar.")
    else:
        meses = fc.meses_disponiveis(tx_all)
        st.markdown(f"**Histórico:** {len(meses)} mês(es) — de {meses[0]} a {meses[-1]}.")

        cfg = store.get_setting("forecast_cfg", {}) or {}
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            months_ahead = st.number_input("Meses a projetar", 1, 12, int(cfg.get("months_ahead", 3)))
        with c2:
            growth = st.number_input("Crescimento mensal (%)", -50.0, 50.0,
                                     float(cfg.get("growth", 0.0)), step=1.0) / 100.0
        with c3:
            base_meses = st.number_input("Base p/ variável (meses)", 1, 12, int(cfg.get("base_meses", 3)))
        with c4:
            min_meses = st.number_input("Mín. meses p/ recorrente", 2, 12, int(cfg.get("min_meses", 2)))
        store.set_setting("forecast_cfg", {"months_ahead": int(months_ahead), "growth": growth,
                                           "base_meses": int(base_meses), "min_meses": int(min_meses)})

        detected = fc.detect_recurring(tx_all, min_meses=int(min_meses))
        overrides = store.load_overrides()
        efetivos = fc.effective_recurring(detected, overrides)

        st.subheader("🔁 Fixos & recorrentes detectados (editável)")
        st.caption("Ligue/desligue, ajuste o valor ou a categoria. Ao salvar, os valores ficam "
                   "fixados na projeção. Use 'Restaurar detecção' para voltar ao automático.")
        if efetivos:
            rec_df = pd.DataFrame(efetivos)[["chave", "ativo", "label", "categoria", "escopo",
                                             "tipo_rec", "valor", "meses"]]
            edited = st.data_editor(
                rec_df, use_container_width=True, hide_index=True, key="rec_editor",
                disabled=["chave", "escopo", "meses"],
                column_config={
                    "chave": None,
                    "ativo": st.column_config.CheckboxColumn("Ativo"),
                    "label": "Item",
                    "categoria": "Categoria",
                    "tipo_rec": st.column_config.SelectboxColumn("Tipo", options=["fixo", "recorrente"]),
                    "valor": st.column_config.NumberColumn("Valor/mês", format="R$ %.2f"),
                    "meses": st.column_config.NumberColumn("Meses vistos"),
                })
            b1, b2 = st.columns([1, 1])
            with b1:
                if st.button("💾 Salvar ajustes dos recorrentes", type="primary"):
                    for _, r in edited.iterrows():
                        store.save_override(r["chave"], r["label"], r["categoria"], r["escopo"],
                                            r["valor"], ativo=bool(r["ativo"]), origem="ajuste")
                    st.success("Ajustes salvos.")
                    st.rerun()
            with b2:
                if st.button("↩️ Restaurar detecção"):
                    for ch in list(overrides.keys()):
                        store.delete_override(ch)
                    st.success("Overrides removidos. Voltando ao detectado.")
                    st.rerun()
            efetivos = fc.effective_recurring(detected, store.load_overrides())
        else:
            st.info("Nenhum recorrente detectado ainda (precisa de gastos repetidos em ≥ 2 meses).")

        # adicionar item manual
        with st.expander("➕ Adicionar gasto fixo manual (ex.: novo custo que ainda não apareceu)"):
            with st.form("novo_fixo"):
                cc = st.columns(4)
                nlabel = cc[0].text_input("Nome")
                ncat = cc[1].text_input("Categoria", value="A classificar")
                nesc = cc[2].selectbox("Escopo", ["PF", "PJ"])
                nval = cc[3].number_input("Valor/mês", 0.0, step=50.0)
                if st.form_submit_button("Adicionar") and nlabel and nval > 0:
                    store.save_override(f"manual|{nesc}|{fc.merchant_key(nlabel)}", nlabel, ncat,
                                        nesc, nval, ativo=True, origem="manual")
                    st.success("Item adicionado.")
                    st.rerun()

        # projeção
        st.divider()
        st.subheader("🔮 Projeção")
        out = fc.project(tx_all, efetivos, months_ahead=int(months_ahead),
                         growth=growth, base_meses=int(base_meses))
        r = out["resumo"]
        if r:
            k = st.columns(4)
            k[0].metric("Fixos/recorrentes /mês", brl(r["fixo_recorrente_mes"]))
            k[1].metric("Variável (base) /mês", brl(r["variavel_baseline_mes"]))
            k[2].metric("Despesa projetada /mês", brl(r["despesa_projetada_mes"]))
            k[3].metric("Resultado projetado /mês", brl(r["resultado_projetado_mes"]))

        hist, proj = out["historico"], out["projecao"]
        if not proj.empty:
            # gráfico histórico + projeção (despesa)
            h = hist[["despesa"]].reset_index().rename(columns={"despesa": "valor"})
            h["tipo"] = "Histórico"
            p = proj[["despesa_total"]].reset_index().rename(columns={"despesa_total": "valor"})
            p["tipo"] = "Projeção"
            serie = pd.concat([h, p], ignore_index=True)
            fig = px.bar(serie, x="mes", y="valor", color="tipo",
                         color_discrete_map={"Histórico": "#2E5496", "Projeção": "#F39C12"})
            fig.update_layout(title="Despesa total: histórico × projeção", xaxis_title="",
                              yaxis_title="", legend_title="", height=380)
            st.plotly_chart(fig, use_container_width=True)

            # composição fixo × variável na projeção
            comp = proj[["fixo_recorrente", "variavel"]].reset_index().melt(
                "mes", var_name="Componente", value_name="Valor")
            fig2 = px.bar(comp, x="mes", y="Valor", color="Componente", barmode="stack",
                          color_discrete_map={"fixo_recorrente": "#1F3864", "variavel": "#8EA9DB"})
            fig2.update_layout(title="Composição da despesa projetada", xaxis_title="",
                               yaxis_title="", legend_title="", height=340)
            st.plotly_chart(fig2, use_container_width=True)

            st.subheader("Tabela da projeção")
            show = proj.copy()
            for c in show.columns:
                show[c] = show[c].map(brl)
            st.dataframe(show, use_container_width=True)

            if not out["por_categoria"].empty:
                st.subheader("Projeção por categoria")
                pc = out["por_categoria"].copy()
                pc = pc.loc[:, pc.sum().sort_values(ascending=False).index]
                st.dataframe(pc.map(brl), use_container_width=True)
