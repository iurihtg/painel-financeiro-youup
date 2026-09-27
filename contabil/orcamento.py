# -*- coding: utf-8 -*-
"""
Planejamento orçamentário — metas de gasto por categoria/subcategoria.

É a tela "Planejamento e Controle" do estilo Meu Planner: você define um teto
planejado por categoria e o sistema mostra o **realizado × planejado** mês a mês,
marcando em vermelho onde estourou, com mín/médio/máximo dos últimos N meses para
ajudar a definir metas factíveis.

O orçamento fica em `settings["orcamento"]` = {categoria: valor_mensal}.
"""
from collections import defaultdict
from datetime import date, datetime


def _mes(d):
    if isinstance(d, (date, datetime)):
        return f"{d.year}-{d.month:02d}"
    s = str(d or "")
    return s[:7] if len(s) >= 7 and s[4] == "-" else None


def meses_disponiveis(tx):
    return sorted({m for t in tx if (m := _mes(t.get("data")))})


def _despesas(tx):
    return [t for t in tx if t.get("tipo") == "Despesa" and float(t.get("saida") or 0) > 0]


def categorias_com_gasto(tx):
    """Categorias que já tiveram despesa (para popular a grade do orçamento)."""
    cats = defaultdict(float)
    for t in _despesas(tx):
        cats[t.get("categoria") or "Sem categoria"] += float(t.get("saida") or 0)
    return [c for c, _ in sorted(cats.items(), key=lambda x: -x[1])]


def realizado_por_mes(tx, categoria):
    """{mes: total gasto} de uma categoria."""
    out = defaultdict(float)
    for t in _despesas(tx):
        if (t.get("categoria") or "Sem categoria") == categoria:
            m = _mes(t.get("data"))
            if m:
                out[m] += float(t.get("saida") or 0)
    return out


def grade(tx, orcamento, mes_ref, janela=3):
    """Uma linha por categoria: planejado, realizado no mês, mín/méd/máx da janela.

    janela: 3, 6 ou 12 — quantos meses (até mes_ref) entram no mín/méd/máx.
    """
    orcamento = orcamento or {}
    meses = meses_disponiveis(tx)
    # janela = os N meses <= mes_ref (inclui o mês de referência)
    janela_meses = [m for m in meses if m <= mes_ref][-janela:] if meses else []

    # categorias: as que têm gasto + as que já têm orçamento definido
    cats = list(dict.fromkeys(categorias_com_gasto(tx) + list(orcamento.keys())))
    linhas = []
    tot_plan = tot_real = 0.0
    for cat in cats:
        rpm = realizado_por_mes(tx, cat)
        real = round(rpm.get(mes_ref, 0.0), 2)
        vals = [rpm.get(m, 0.0) for m in janela_meses]
        minv = round(min(vals), 2) if vals else 0.0
        maxv = round(max(vals), 2) if vals else 0.0
        med = round(sum(vals) / len(vals), 2) if vals else 0.0
        plan = round(float(orcamento.get(cat) or 0), 2)
        pct = round(real / plan * 100, 0) if plan > 0 else None
        linhas.append({
            "categoria": cat, "planejado": plan, "realizado": real,
            "media": med, "min": minv, "max": maxv,
            "pct": pct, "estourou": (plan > 0 and real > plan),
        })
        tot_plan += plan
        tot_real += real
    totais = {"planejado": round(tot_plan, 2), "realizado": round(tot_real, 2),
              "estourou": tot_plan > 0 and tot_real > tot_plan}
    return linhas, totais, janela_meses


def _eh_cartao(fonte, cartoes_reg=None):
    f = (fonte or "").lower()
    if "cart" in f:
        return True
    for nome in (cartoes_reg or []):
        if (nome or "").lower() == f:
            return True
    return False


def cartoes_por_mes(tx, meses=None, cartoes_reg=None):
    """Matriz cartão × mês (gasto). Devolve (cartoes, meses, {cartao:{mes:val}}, totais_mes)."""
    desp = _despesas(tx)
    if meses is None:
        meses = meses_disponiveis(tx)[-6:]
    mat = defaultdict(lambda: defaultdict(float))
    for t in desp:
        f = t.get("fonte") or "—"
        if _eh_cartao(f, cartoes_reg):
            m = _mes(t.get("data"))
            if m in meses:
                mat[f][m] += float(t.get("saida") or 0)
    cartoes = sorted(mat.keys(), key=lambda c: -sum(mat[c].values()))
    tot_mes = {m: round(sum(mat[c].get(m, 0) for c in cartoes), 2) for m in meses}
    matriz = {c: {m: round(mat[c].get(m, 0), 2) for m in meses} for c in cartoes}
    return cartoes, meses, matriz, tot_mes
