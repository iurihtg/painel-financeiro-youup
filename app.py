# -*- coding: utf-8 -*-
"""
Painel Financeiro Youup — interface Streamlit.

Abas:
  🎨 Painel      — as 5 telas bonitas (Balanço, Análises, Contas, Investimentos, Planos)
  ✍️ Lançamentos — adicionar receitas/despesas (à mão, por frase ou importando) e editar tudo
  🔁 Duplicações — motor anti-duplicação: pega o mesmo dinheiro contado 2x
  ⚙️ Cadastros   — categorias/subcategorias, contas/cartões/bancos, contas a pagar, investimentos, planos

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
from contabil import reconciliar
from contabil import assistente
from contabil import orcamento as _orc_mod
import streamlit.components.v1 as components

_MESES_PT = {1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
             7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"}


def _hoje_br():
    """Data de hoje no fuso do Brasil (o servidor roda em UTC)."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    except Exception:
        return dt.date.today()


def _mes_label(m):
    try:
        y, mo = m.split("-")
        return f"{_MESES_PT[int(mo)]} {y}"
    except Exception:
        return m

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


# ── carrega o histórico UMA vez por rerun (menos chamadas ao backend) ──
try:
    TX = store.load_transactions()
    _erro_banco = None
except Exception as e:  # noqa
    TX, _erro_banco = [], e


def opcoes_categorias():
    """Categorias-padrão + as que o Iuri cadastrou (com subcategorias) + as já usadas."""
    opts = set(DEFAULT_CATEGORIES)
    for c in (store.get_setting("categorias", []) or []):
        nome = (c.get("nome") or "").strip()
        if nome:
            opts.add(nome)
            for s in c.get("subs", []) or []:
                if s:
                    opts.add(f"{nome} › {s}")
    opts |= {t.get("categoria") for t in TX if t.get("categoria")}
    return sorted(o for o in opts if o)


def opcoes_contas():
    """Contas/cartões cadastrados + as origens já usadas + algumas padrão."""
    reg = [c.get("nome") for c in (store.get_setting("contas_reg", []) or []) if c.get("nome")]
    usadas = [t.get("fonte") for t in TX if t.get("fonte")]
    base = ["Manual", "WhatsApp", "Dinheiro", "Pix"]
    return sorted(set([n for n in reg + usadas + base if n]))


# ── sidebar ──
if _erro_banco:
    st.sidebar.error(f"Banco indisponível: {_erro_banco}")
st.sidebar.title("Youup Finanças")
st.sidebar.metric("Lançamentos no histórico", f"{len(TX):,}".replace(",", "."))
st.sidebar.caption(f"Backend: {db.backend_nome()}")

_resolv = store.get_setting("dedup_resolvidos", {}) or {}
_sus = reconciliar.detectar(TX, _resolv) if TX else []
if _sus:
    st.sidebar.warning(f"🔁 {len(_sus)} possível(is) duplicação(ões) — veja a aba **Duplicações**")

st.sidebar.divider()
st.sidebar.markdown(
    "**Como alimentar o sistema:**\n\n"
    "1. **✍️ Lançamentos** → à mão, **por frase** (\"gastei 50 no ifood\") ou importe OFX/PDF/Excel.\n"
    "2. **📊 Orçamento** → defina o teto de gasto por categoria e veja realizado × planejado.\n"
    "3. **🔁 Duplicações** → confirme transferências para não contar o mesmo dinheiro 2x.\n"
    "4. **⚙️ Cadastros** → categorias, contas/cartões, contas a pagar, investimentos, metas.\n"
    "5. **🎨 Painel** → veja tudo bonito e atualizado."
)

tab_painel, tab_lanc, tab_orc, tab_dup, tab_cad = st.tabs(
    ["🎨 Painel", "✍️ Lançamentos", "📊 Orçamento", "🔁 Duplicações", "⚙️ Cadastros"])

# ═══════════════════════════ 🎨 PAINEL ═══════════════════════════
with tab_painel:
    _contas = store.get_setting("contas", []) or []
    _invs = store.get_setting("investimentos", []) or []
    _meta = store.get_setting("meta_patrimonio", 11_000_000)
    _planos = store.get_setting("planos", []) or []
    _orcamento = store.get_setting("orcamento", {}) or {}
    _dados = _painel.compute_dados(TX, _contas, _invs, _meta, _planos,
                                   orcamento=_orcamento, hoje=_hoje_br())
    components.html(_painel.render(_dados), height=920, scrolling=True)

# ═══════════════════════════ ✍️ LANÇAMENTOS ═══════════════════════════
with tab_lanc:
    _cats = opcoes_categorias()
    _contas_opt = opcoes_contas()

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
        _lfonte = m3.selectbox("Conta / origem", _contas_opt,
                               index=(_contas_opt.index("Manual") if "Manual" in _contas_opt else 0))
        if st.form_submit_button("➕ Adicionar", type="primary") and _lval > 0:
            _novo = {"data": _ldata.isoformat(), "escopo": "PF" if _lesc.startswith("PF") else "PJ",
                     "fonte": _lfonte or "Manual", "descricao": _ldesc or _lcat,
                     "entrada": float(_lval) if _ltipo == "Receita" else 0.0,
                     "saida": float(_lval) if _ltipo == "Despesa" else 0.0,
                     "tipo": _ltipo, "categoria": _lcat, "obs": "manual"}
            ins, ign = store.save_transactions([_novo])
            st.success("Lançamento adicionado." if ins else "Esse lançamento já existia.")
            st.rerun()

    with st.expander("🗣️ Lançar por frase (prévia da IA do WhatsApp)"):
        st.caption("Escreva como você falaria. Ex.: \"gastei 50 no ifood\", "
                   "\"recebi 1200 na maquininha\", \"1500 aluguel ontem\".")
        _frase = st.text_input("Frase", key="frase_nl", label_visibility="collapsed",
                               placeholder="gastei 50 no ifood")
        if _frase:
            _in = assistente.interpretar(_frase)
            if not _in["ok"]:
                st.error(_in["aviso"])
            else:
                st.markdown(f"→ **{_in['tipo']}** de **{brl(_in['valor'])}** · {_in['categoria']} "
                            f"· {_in['escopo']} · {_in['data']}")
                if _in.get("aviso"):
                    st.info(_in["aviso"])
                if st.button("💾 Salvar esse lançamento", key="save_nl", type="primary"):
                    store.save_transactions([assistente.para_lancamento(_in)])
                    st.success("Salvo!")
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
    if not TX:
        st.info("Nenhum lançamento ainda. Adicione acima ou importe um arquivo.")
    else:
        so_class = st.checkbox("Mostrar só os 'A classificar'", value=False)
        dfa = pd.DataFrame(TX)
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

# ═══════════════════════════ 📊 ORÇAMENTO ═══════════════════════════
with tab_orc:
    st.subheader("📊 Planejamento e Controle")
    st.caption("Planilha estilo Meu Planner: você edita só o **Planejamento** (teto/mês); "
               "**% · Mín · Méd · Máx** e os meses são calculados. 🔴 = passou do planejado no mês.")
    _orc = store.get_setting("orcamento", {}) or {}
    om1, om2 = st.columns([2, 2])
    _jan = om1.selectbox("Base do Mín/Méd/Máx", [3, 6, 12], index=0,
                         format_func=lambda n: f"últimos {n} meses")
    _nm = om2.selectbox("Meses na planilha", [6, 12, 24], index=0,
                        format_func=lambda n: f"últimos {n} meses")
    _pdados = _orc_mod.montar_planejamento(TX, _orc, hoje=_hoje_br(), janela=_jan, n_meses=_nm)

    # editor enxuto: só os tetos (a "coluna azul" editável)
    with st.expander("✏️ Editar os tetos (Planejamento por categoria/subcategoria)", expanded=not _orc):
        st.caption("Digite o teto mensal de cada item e salve. Deixe 0 para 'sem meta'. "
                   "Para criar subcategorias, cadastre em ⚙️ Cadastros (viram \"Categoria › Sub\").")
        _eds = _pdados["editaveis"]
        if not _eds:
            st.info("Sem categorias ainda — faça lançamentos ou cadastre categorias.")
        else:
            _dfe = pd.DataFrame([{"Seção": e["secao"], "Item": e["label"],
                                  "Planejado": e["planejado"]} for e in _eds])
            _ede = st.data_editor(
                _dfe, hide_index=True, use_container_width=True, height=300, key="orc_tetos",
                disabled=["Seção", "Item"],
                column_config={"Planejado": st.column_config.NumberColumn(
                    "Planejado (R$/mês)", format="R$ %.2f", min_value=0.0, step=50.0)})
            if st.button("💾 Salvar planejamento", type="primary"):
                _novo = dict(_orc)
                for _, r in _ede.iterrows():
                    v = float(r["Planejado"] or 0)
                    if v > 0:
                        _novo[r["Item"]] = round(v, 2)
                    elif r["Item"] in _novo:
                        del _novo[r["Item"]]
                store.set_setting("orcamento", _novo)
                st.success("Planejamento salvo. A planilha e o painel já usam esses tetos.")
                st.rerun()

    # a planilha bonita (leitura), estilo Meu Planner
    _alt = min(900, 190 + (len(_pdados["receita"]["linhas"]) + len(_pdados["despesa"]["linhas"]) + 3) * 34)
    components.html(_orc_mod.render_planejamento(_pdados), height=_alt, scrolling=True)

    st.divider()
    st.subheader("💳 Controle de cartões")
    _cart_reg = [c.get("nome") for c in (store.get_setting("contas_reg", []) or [])
                 if c.get("tipo") == "Cartão de crédito" and c.get("nome")]
    _cartoes, _cmeses, _matriz, _totmes = _orc_mod.cartoes_por_mes(TX, cartoes_reg=_cart_reg)
    if not _cartoes:
        st.info("Nenhum gasto em cartão identificado ainda. Dica: cadastre seus cartões em "
                "⚙️ Cadastros (tipo **Cartão de crédito**) e importe as faturas — aí cada "
                "cartão aparece aqui com o gasto mês a mês.")
    else:
        _rows = []
        for c in _cartoes:
            row = {"Cartão": c}
            for m in _cmeses:
                row[_mes_label(m).split()[0][:3] + "/" + m[2:4]] = _matriz[c].get(m, 0.0)
            row["Total"] = round(sum(_matriz[c].values()), 2)
            _rows.append(row)
        _tot_row = {"Cartão": "TOTAL"}
        for m in _cmeses:
            _tot_row[_mes_label(m).split()[0][:3] + "/" + m[2:4]] = _totmes.get(m, 0.0)
        _tot_row["Total"] = round(sum(_totmes.values()), 2)
        _rows.append(_tot_row)
        _dfc = pd.DataFrame(_rows)
        _numcols = [c for c in _dfc.columns if c != "Cartão"]
        st.dataframe(_dfc, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="R$ %.2f") for c in _numcols})
        st.caption("💡 Para melhorar o controle de cartões: cadastre cada cartão em Cadastros "
                   "(com banco e escopo PF/PJ), e registre o **limite** e o **vencimento** da fatura "
                   "em ⚙️ Cadastros → Contas a pagar. Assim dá pra alertar antes de estourar o limite.")

# ═══════════════════════════ 🔁 DUPLICAÇÕES ═══════════════════════════
with tab_dup:
    st.subheader("🔁 Conferência anti-duplicação")
    st.caption("O sistema procura o **mesmo dinheiro contado duas vezes**: transferências "
               "entre suas contas (ex.: recebe na maquininha PJ → transfere pra conta PF) e "
               "lançamentos repetidos. Nada é alterado sem você confirmar aqui.")
    if not _sus:
        st.success("Nenhuma duplicação pendente. Seus números não estão inflados. ✅")
    else:
        st.warning(reconciliar.resumo(_sus))
        for s in _sus:
            with st.container(border=True):
                titulo = "🔄 Transferência interna" if s["kind"] == "transferencia" else "👯 Duplicata"
                st.markdown(f"**{titulo}** · **{brl(s['valor'])}** · confiança _{s['confianca']}_")
                st.caption(s["motivo"])
                for lg in s["legs"]:
                    seta = "🔻 saiu" if lg["direcao"] == "saída" else "🔺 entrou"
                    st.write(f"• {lg['data']} · {seta} · **{lg['conta']}** · {lg['descricao']} "
                             f"· {brl(lg['valor'])}")
                col = st.columns([2, 2, 3])
                if s["kind"] == "transferencia":
                    if col[0].button("✅ É transferência (não contar 2x)",
                                     key="neu_" + s["sig"], type="primary"):
                        for _id in s["ids"]:
                            store.set_tipo(_id, reconciliar.TIPO_INTERNO)
                        _resolv[s["sig"]] = "neutralizado"
                        store.set_setting("dedup_resolvidos", _resolv)
                        st.rerun()
                else:
                    if col[0].button("🗑️ Apagar as cópias (manter 1)",
                                     key="del_" + s["sig"], type="primary"):
                        for _id in s["ids"][1:]:
                            store.delete_transaction(_id)
                        _resolv[s["sig"]] = "neutralizado"
                        store.set_setting("dedup_resolvidos", _resolv)
                        st.rerun()
                if col[1].button("↔️ São coisas diferentes", key="ig_" + s["sig"]):
                    _resolv[s["sig"]] = "ignorado"
                    store.set_setting("dedup_resolvidos", _resolv)
                    st.rerun()
    if _resolv:
        st.divider()
        st.caption(f"{len(_resolv)} decisão(ões) já tomada(s).")
        if st.button("↩️ Rever tudo de novo (limpar decisões)"):
            store.set_setting("dedup_resolvidos", {})
            st.rerun()

# ═══════════════════════════ ⚙️ CADASTROS ═══════════════════════════
with tab_cad:
    _contas = store.get_setting("contas", []) or []
    _invs = store.get_setting("investimentos", []) or []
    _meta = store.get_setting("meta_patrimonio", 11_000_000)
    _planos = store.get_setting("planos", []) or []

    # ── categorias e subcategorias ──
    st.subheader("🏷️ Categorias e subcategorias")
    st.caption("Crie suas categorias. Subcategorias aparecem no menu como \"Categoria › Sub\".")
    st.caption("📌 **Exemplo:** categoria _Alimentação_ · subcategorias _Restaurante, Supermercado, iFood_")
    _cats_user = store.get_setting("categorias", []) or []
    with st.form("nova_cat", clear_on_submit=True):
        a, b = st.columns([2, 3])
        _cn = a.text_input("Nova categoria")
        _cs = b.text_input("Subcategorias (separe por vírgula)")
        if st.form_submit_button("➕ Adicionar categoria") and _cn.strip():
            subs = [s.strip() for s in _cs.split(",") if s.strip()]
            for c in _cats_user:
                if (c.get("nome") or "").lower() == _cn.strip().lower():
                    c["subs"] = sorted(set((c.get("subs") or []) + subs))
                    break
            else:
                _cats_user.append({"nome": _cn.strip(), "subs": subs})
            store.set_setting("categorias", _cats_user)
            st.rerun()
    if _cats_user:
        for c in _cats_user:
            cc = st.columns([2, 3, 1])
            cc[0].write(f"**{c.get('nome')}**")
            cc[1].write(", ".join(c.get("subs") or []) or "—")
            if cc[2].button("🗑️", key="delcat_" + (c.get("nome") or "")):
                store.set_setting("categorias", [x for x in _cats_user if x.get("nome") != c.get("nome")])
                st.rerun()
    else:
        st.info("Ainda usando só as categorias-padrão. Crie as suas acima quando quiser.")

    st.divider()
    # ── contas, cartões e bancos ──
    st.subheader("🏦 Contas, cartões e bancos")
    st.caption("Cadastre suas contas e cartões — eles viram opções no campo \"Conta / origem\".")
    st.caption("📌 **Exemplo:** _Cartão Nubank_ · tipo _Cartão de crédito_ · banco _Nubank_ · escopo _PF_")
    _contas_reg = store.get_setting("contas_reg", []) or []
    with st.form("nova_contareg", clear_on_submit=True):
        a, b, c, d = st.columns([2, 1.4, 1.4, 1.2])
        _rn = a.text_input("Nome (ex.: Itaú CC, Cartão Nubank, Cora)")
        _rt = b.selectbox("Tipo", ["Conta corrente", "Cartão de crédito", "Maquininha",
                                   "Dinheiro", "Investimento", "Poupança"])
        _rb = c.text_input("Banco / emissor")
        _re = d.selectbox("Escopo", ["PF (Iuri)", "PJ (Youup)"])
        if st.form_submit_button("➕ Adicionar conta/cartão") and _rn.strip():
            _contas_reg.append({"id": uuid.uuid4().hex[:8], "nome": _rn.strip(), "tipo": _rt,
                                "banco": _rb.strip(), "escopo": "PF" if _re.startswith("PF") else "PJ"})
            store.set_setting("contas_reg", _contas_reg)
            st.rerun()
    if _contas_reg:
        for c in _contas_reg:
            cc = st.columns([2, 1.6, 1.6, 0.8, 0.6])
            cc[0].write(f"**{c.get('nome')}**")
            cc[1].write(c.get("tipo") or "—")
            cc[2].write(c.get("banco") or "—")
            cc[3].write(c.get("escopo") or "—")
            if cc[4].button("🗑️", key="delreg_" + c["id"]):
                store.set_setting("contas_reg", [x for x in _contas_reg if x.get("id") != c["id"]])
                st.rerun()
    else:
        st.info("Nenhuma conta/cartão cadastrado. Cadastre para facilitar os lançamentos.")

    st.divider()
    st.subheader("📅 Contas a pagar / receber")
    st.caption("📌 **Exemplo:** _A pagar_ · _Aluguel_ · R$ 2.500 · categoria _Moradia_ · vence _05/10/2026_")
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
    st.caption("📌 **Exemplo:** _BTG_ · _Renda Fixa_ · ativo _CDB 110% CDI_ · investido R$ 10.000 · saldo R$ 10.850")
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
    st.caption("📌 **Exemplo:** _Reserva de emergência_ · _Meta (guardar)_ · total R$ 60.000 · "
               "já guardado R$ 15.000 · aporte R$ 2.000/mês")
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
