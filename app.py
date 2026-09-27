# -*- coding: utf-8 -*-
"""
Painel Financeiro Youup — interface Streamlit.

Abas:
  🎨 Painel      — as 5 telas bonitas (Balanço, Análises, Contas, Investimentos, Planos)
  ✍️ Lançamentos — adicionar receitas/despesas manualmente, importar arquivos e editar tudo
  ⚙️ Cadastros   — contas a pagar/receber, investimentos e planos/metas

Rodar:  streamlit run app.py
"""
import os
import uuid
import tempfile
import datetime as dt

import pandas as pd
import streamlit as st

from contabil.pipeline import process, modelo_excel_bytes, DEFAULT_CATEGORIES
from contabil.build import build_workbook
from contabil import db
from contabil import painel as _painel
import streamlit.components.v1 as components

st.set_page_config(page_title="Painel Financeiro Youup", page_icon="📊", layout="wide")


def _secret(chave, default=None):
    if os.environ.get(chave):
        return os.environ[chave]
    try:
        return st.secrets[chave]
    except Exception:
        return default


for _k in ("SUPABASE_URL", "SUPABASE_KEY"):
    _v = _secret(_k)
    if _v and not os.environ.get(_k):
        os.environ[_k] = str(_v)

_SENHA = _secret("APP_SENHA")
if _SENHA and not st.session_state.get("_ok"):
    st.title("🔒 Painel Financeiro")
    _t = st.text_input("Senha de acesso", type="password")
    if _t == _SENHA:
        st.session_state["_ok"] = True
        st.rerun()
    elif _t:
        st.error("Senha incorreta.")
    st.stop()

store = db.active()


def brl(v):
    try:
        return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"


def categorias_disponiveis(tx):
    cats = set(DEFAULT_CATEGORIES)
    cats |= {t.get("categoria") for t in tx if t.get("categoria")}
    return sorted(c for c in cats if c)


# ── sidebar ──
try:
    n_hist = store.count_transactions()
except Exception as e:
    n_hist = 0
    st.sidebar.error(f"Banco indisponível: {e}")
st.sidebar.title("Youup Finanças")
st.sidebar.metric("Lançamentos no histórico", f"{n_hist:,}".replace(",", "."))
st.sidebar.caption(f"Backend: {db.backend_nome()}")
st.sidebar.divider()
st.sidebar.markdown(
    "**Como alimentar o sistema:**\n\n"
    "1. **✍️ Lançamentos** → adicione à mão *ou* importe OFX/PDF/Excel.\n"
    "2. **⚙️ Cadastros** → contas a pagar/receber, investimentos e metas.\n"
    "3. **🎨 Painel** → veja tudo bonito e atualizado."
)

tab_painel, tab_lanc, tab_cad = st.tabs(["🎨 Painel", "✍️ Lançamentos", "⚙️ Cadastros"])

# ═══════════════════════════ 🎨 PAINEL ═══════════════════════════
with tab_painel:
    _tx = store.load_transactions()
    _contas = store.get_setting("contas", []) or []
    _invs = store.get_setting("investimentos", []) or []
    _meta = store.get_setting("meta_patrimonio", 11_000_000)
    _planos = store.get_setting("planos", []) or []
    _dados = _painel.compute_dados(_tx, _contas, _invs, _meta, _planos)
    components.html(_painel.render(_dados), height=920, scrolling=True)

# ═══════════════════════════ ✍️ LANÇAMENTOS ═══════════════════════════
with tab_lanc:
    _tx_all = store.load_transactions()
    _cats = categorias_disponiveis(_tx_all)

    st.subheader("➕ Adicionar lançamento manual")
    with st.form("novo_lanc", clear_on_submit=True):
        l1, l2, l3, l4 = st.columns([1, 1, 1, 1])
        _ldata = l1.date_input("Data", value=dt.date.today())
        _ltipo = l2.selectbox("Tipo", ["Despesa", "Receita"])
        _lval = l3.number_input("Valor (R$)", min_value=0.0, step=10.0)
        _lesc = l4.selectbox("Escopo", ["PF (Iuri)", "PJ (Youup)"])
        m1, m2, m3 = st.columns([2, 2, 1.4])
        _ldesc = m1.text_input("Descrição")
        _lcat = m2.selectbox("Categoria", _cats,
                             index=(_cats.index("A classificar") if "A classificar" in _cats else 0))
        _lfonte = m3.text_input("Conta / origem", value="Manual")
        if st.form_submit_button("➕ Adicionar", type="primary") and _lval > 0:
            _novo = {"data": _ldata.isoformat(), "escopo": "PF" if _lesc.startswith("PF") else "PJ",
                     "fonte": _lfonte or "Manual", "descricao": _ldesc or _lcat,
                     "entrada": float(_lval) if _ltipo == "Receita" else 0.0,
                     "saida": float(_lval) if _ltipo == "Despesa" else 0.0,
                     "tipo": _ltipo, "categoria": _lcat, "obs": "manual"}
            ins, ign = store.save_transactions([_novo])
            st.success("Lançamento adicionado." if ins else "Esse lançamento já existia.")
            st.rerun()

    st.divider()
    st.subheader("📥 Importar arquivos (OFX / PDF / Excel)")
    with st.expander("O que dá pra importar / baixar o modelo"):
        st.markdown(
            "- **OFX (recomendado):** extrato do mês inteiro, exportado no Internet Banking.\n"
            "- **PDF:** faturas/extratos Itaú, BTG, Caixa, Mercado Pago, Cora, PagBank.\n"
            "- **Excel-modelo:** colunas Data / Descrição / Valor (plano B universal)."
        )
        st.download_button("⬇️ Baixar planilha-modelo", data=modelo_excel_bytes(),
                           file_name="modelo_lancamentos.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    files = st.file_uploader("Arquivos", type=["ofx", "pdf", "xlsx", "xlsm"], accept_multiple_files=True)
    if st.button("Processar arquivos", disabled=not files):
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for f in files:
                p = os.path.join(tmp, f.name)
                with open(p, "wb") as out:
                    out.write(f.getbuffer())
                paths.append(p)
            with st.spinner("Processando…"):
                tx, rep = process(paths)
            st.session_state["tx_proc"] = tx
            st.session_state["rep"] = rep
    if "tx_proc" in st.session_state:
        tx, rep = st.session_state["tx_proc"], st.session_state["rep"]
        st.success(f"{rep['total']} lançamentos lidos neste lote.")
        cc1, cc2 = st.columns(2)
        cc1.dataframe(pd.DataFrame(rep["arquivos"]), use_container_width=True, hide_index=True)
        cc2.dataframe(pd.DataFrame(rep["por_fonte"]), use_container_width=True, hide_index=True)
        if rep["ignorados"]:
            st.warning("Não reconhecidos: " + ", ".join(rep["ignorados"]))
        if st.button("💾 Salvar no histórico", type="primary"):
            ins, ign = store.save_transactions(tx)
            st.success(f"{ins} novos salvos, {ign} já existiam.")
            del st.session_state["tx_proc"]
            st.rerun()

    st.divider()
    st.subheader("📋 Todos os lançamentos")
    if not _tx_all:
        st.info("Nenhum lançamento ainda. Adicione acima ou importe um arquivo.")
    else:
        so_class = st.checkbox("Mostrar só os 'A classificar'", value=False)
        dfa = pd.DataFrame(_tx_all)
        dfa["data"] = pd.to_datetime(dfa["data"], errors="coerce")
        dfa = dfa.sort_values("data", ascending=False)
        if so_class:
            dfa = dfa[dfa["categoria"] == "A classificar"]
        show = pd.DataFrame({
            "Excluir": False, "id": dfa["id"],
            "Data": dfa["data"].dt.strftime("%d/%m/%Y"), "Tipo": dfa["tipo"],
            "Escopo": dfa["escopo"], "Conta": dfa["fonte"], "Descrição": dfa["descricao"],
            "Categoria": dfa["categoria"],
            "Entrada": pd.to_numeric(dfa["entrada"], errors="coerce").fillna(0.0),
            "Saída": pd.to_numeric(dfa["saida"], errors="coerce").fillna(0.0),
        })
        st.caption(f"{len(show)} lançamento(s). Edite a categoria ou marque 🗑️ e salve.")
        edited = st.data_editor(
            show, hide_index=True, use_container_width=True, height=430, key="lanc_editor",
            disabled=["id", "Data", "Tipo", "Escopo", "Conta", "Descrição", "Entrada", "Saída"],
            column_config={
                "id": None,
                "Excluir": st.column_config.CheckboxColumn("🗑️", width="small"),
                "Categoria": st.column_config.SelectboxColumn("Categoria", options=_cats),
                "Entrada": st.column_config.NumberColumn(format="R$ %.2f"),
                "Saída": st.column_config.NumberColumn(format="R$ %.2f"),
            })
        if st.button("💾 Salvar alterações", type="primary"):
            orig = dict(zip(show["id"], show["Categoria"]))
            ncat = ndel = 0
            for _, r in edited.iterrows():
                if r["Excluir"]:
                    store.delete_transaction(r["id"]); ndel += 1
                elif r["Categoria"] != orig.get(r["id"]):
                    store.set_categoria_manual(r["id"], r["Categoria"]); ncat += 1
            st.success(f"{ncat} categoria(s) alterada(s), {ndel} excluído(s).")
            st.rerun()

# ═══════════════════════════ ⚙️ CADASTROS ═══════════════════════════
with tab_cad:
    _contas = store.get_setting("contas", []) or []
    _invs = store.get_setting("investimentos", []) or []
    _meta = store.get_setting("meta_patrimonio", 11_000_000)
    _planos = store.get_setting("planos", []) or []

    st.subheader("📅 Contas a pagar / receber")
    with st.form("nova_conta", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 2, 1])
        _tipo = c1.selectbox("Tipo", ["A pagar", "A receber"])
        _desc = c2.text_input("Descrição")
        _val = c3.number_input("Valor (R$)", min_value=0.0, step=50.0)
        c4, c5 = st.columns(2)
        _cat = c4.text_input("Categoria", value="")
        _venc = c5.date_input("Vencimento", value=dt.date.today())
        if st.form_submit_button("➕ Adicionar conta") and _desc and _val > 0:
            _contas.append({"id": uuid.uuid4().hex[:8],
                            "tipo": "pagar" if _tipo == "A pagar" else "receber",
                            "desc": _desc, "cat": _cat, "valor": float(_val),
                            "venc": _venc.isoformat(), "status": "pendente"})
            store.set_setting("contas", _contas)
            st.rerun()
    _pend = [c for c in _contas if c.get("status", "pendente") == "pendente"]
    if _pend:
        for c in sorted(_pend, key=lambda x: str(x.get("venc", ""))):
            cc = st.columns([3, 1, 1])
            v = c.get("venc", "")
            cc[0].write(f"**{c.get('desc')}** · {c.get('cat') or '—'} · vence {v[8:10]}/{v[5:7]}")
            cc[1].write(("−" if c["tipo"] == "pagar" else "+") + " " + brl(c.get("valor")))
            if cc[2].button("✓ Baixar", key="baixa_" + c["id"]):
                for x in _contas:
                    if x.get("id") == c["id"]:
                        x["status"] = "pago"
                store.set_setting("contas", _contas)
                st.rerun()
    else:
        st.info("Sem contas pendentes.")

    st.divider()
    st.subheader("💰 Investimentos")
    _meta_nova = st.number_input("🎯 Meta de patrimônio (independência financeira)",
                                 min_value=0, value=int(_meta), step=100_000, format="%d")
    if _meta_nova != _meta:
        store.set_setting("meta_patrimonio", int(_meta_nova))
        st.rerun()
    with st.form("novo_inv", clear_on_submit=True):
        i1, i2, i3 = st.columns([2, 1, 1])
        _inst = i1.text_input("Instituição / corretora")
        _itipo = i2.selectbox("Tipo", ["Renda Fixa", "Renda Variável"])
        _emis = i3.text_input("Emissor / ativo")
        i4, i5 = st.columns(2)
        _iinv = i4.number_input("Valor investido (R$)", min_value=0.0, step=100.0)
        _isaldo = i5.number_input("Saldo atual (R$)", min_value=0.0, step=100.0)
        if st.form_submit_button("➕ Adicionar investimento") and _inst and _isaldo > 0:
            _invs.append({"id": uuid.uuid4().hex[:8], "instituicao": _inst, "tipo": _itipo,
                          "emissor": _emis, "produto": _emis, "investido": float(_iinv),
                          "saldo": float(_isaldo)})
            store.set_setting("investimentos", _invs)
            st.rerun()
    if _invs:
        for it in _invs:
            ic = st.columns([3, 1.4, 1])
            ic[0].write(f"**{it.get('emissor') or it.get('instituicao')}** · {it.get('tipo')} · {it.get('instituicao')}")
            novo = ic[1].number_input("Saldo", min_value=0.0, value=float(it.get("saldo") or 0),
                                      step=100.0, key="sld_" + it["id"], label_visibility="collapsed")
            if novo != float(it.get("saldo") or 0):
                it["saldo"] = float(novo)
                store.set_setting("investimentos", _invs)
                st.rerun()
            if ic[2].button("🗑️", key="del_" + it["id"]):
                store.set_setting("investimentos", [x for x in _invs if x.get("id") != it["id"]])
                st.rerun()
    else:
        st.info("Sem investimentos cadastrados.")

    st.divider()
    st.subheader("🎯 Planos & Metas")
    with st.form("novo_plano", clear_on_submit=True):
        p1, p2 = st.columns([2, 1])
        _pnome = p1.text_input("Nome do plano (ex.: Reserva, Quitar carro, Independência 11mi)")
        _ptipo = p2.selectbox("Tipo", ["Meta (guardar)", "Dívida (quitar)"])
        p3, p4, p5 = st.columns(3)
        _ptotal = p3.number_input("Valor total (R$)", min_value=0.0, step=500.0)
        _parr = p4.number_input("Já guardado (R$)", min_value=0.0, step=500.0)
        _pparc = p5.number_input("Aporte por mês (R$)", min_value=0.0, step=100.0)
        if st.form_submit_button("➕ Criar plano") and _pnome and _ptotal > 0:
            _planos.append({"id": uuid.uuid4().hex[:8], "nome": _pnome,
                            "tipo": "divida" if _ptipo.startswith("Dívida") else "meta",
                            "total": float(_ptotal), "arrecadado": float(_parr), "parcela": float(_pparc)})
            store.set_setting("planos", _planos)
            st.rerun()
    if _planos:
        for p in _planos:
            pc = st.columns([3, 1.3, 1, 1])
            _tot, _ar = float(p.get("total") or 0), float(p.get("arrecadado") or 0)
            _pctp = int(_ar / _tot * 100) if _tot else 0
            pc[0].write(f"**{p.get('nome')}** · {_pctp}% · {brl(_ar)} / {brl(_tot)}")
            _ap = pc[1].number_input("Aportar", min_value=0.0, step=100.0,
                                     key="ap_" + p["id"], label_visibility="collapsed")
            if pc[2].button("💰 Aportar", key="apb_" + p["id"]) and _ap > 0:
                p["arrecadado"] = _ar + float(_ap)
                store.set_setting("planos", _planos)
                st.rerun()
            if pc[3].button("🗑️", key="delp_" + p["id"]):
                store.set_setting("planos", [x for x in _planos if x.get("id") != p["id"]])
                st.rerun()
    else:
        st.info("Sem planos cadastrados. Crie um (ex.: sua meta dos 11 milhões).")
