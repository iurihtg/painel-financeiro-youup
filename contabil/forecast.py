# -*- coding: utf-8 -*-
"""
Detecção de gastos fixos/recorrentes e projeção de despesas.

Ideia central (e por que evita dupla contagem):
  - Agrupa as DESPESAS por "comerciante" (chave derivada da descrição) e mês.
  - Um grupo que aparece em >= `min_meses` meses é RECORRENTE. Se o valor é
    quase constante (baixa variação) é "fixo" (financiamento, condomínio,
    software); senão é "recorrente" variável (assinatura que oscila).
  - Projeção de cada mês futuro = (soma dos recorrentes ATIVOS, editáveis)
    + (linha de base dos gastos VARIÁVEIS). A linha de base variável é a média
    recente de (despesa total do mês − despesa recorrente daquele mês), então
    o que já está nos recorrentes NÃO é contado de novo.

Tudo que a UI edita (valor de um fixo, ativar/desativar, adicionar item,
crescimento %, meses à frente) entra aqui via `effective_recurring` e os
parâmetros de `project`.
"""
import re
import unicodedata
from collections import defaultdict
from datetime import date

import pandas as pd

# tokens de ruído que não ajudam a identificar o comerciante
_STOP = {"ltda", "me", "sa", "s", "a", "de", "da", "do", "das", "dos", "e", "em",
         "com", "br", "bra", "brasil", "pagamento", "compra", "parcela", "mensalidade",
         "servico", "servicos", "ltda.", "eireli", "cia"}


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def merchant_key(desc):
    """Chave estável de comerciante a partir da descrição (sem números/ruído)."""
    d = _norm(desc)
    d = re.sub(r"\d+", " ", d)                    # tira números (datas, parcelas, ids)
    d = re.sub(r"[^a-z ]", " ", d)                # só letras
    toks = [w for w in d.split() if w and w not in _STOP and len(w) > 1]
    if not toks:
        return _norm(desc)[:24] or "sem-descricao"
    return " ".join(toks[:4])


def _label(desc):
    return " ".join(w.capitalize() for w in merchant_key(desc).split()) or str(desc)[:30]


def _mes(d):
    """Retorna 'YYYY-MM' a partir de date ou string ISO; None se inválido."""
    if isinstance(d, date):
        return f"{d.year}-{d.month:02d}"
    s = str(d or "")
    return s[:7] if len(s) >= 7 and s[4] == "-" else None


def _is_despesa(t):
    return (t.get("tipo") == "Despesa") and float(t.get("saida") or 0) > 0


# ───────────────────────── matrizes mensais ─────────────────────────
def monthly_matrix(tx, tipo="Despesa", valor_campo="saida"):
    """DataFrame: linhas=mês (YYYY-MM), colunas=categoria, valores=soma. Ordenado por mês."""
    agg = defaultdict(float)
    for t in tx:
        if t.get("tipo") != tipo:
            continue
        v = float(t.get(valor_campo) or 0)
        if v <= 0:
            continue
        m = _mes(t.get("data"))
        if not m:
            continue
        agg[(m, t.get("categoria") or "Sem categoria")] += v
    if not agg:
        return pd.DataFrame()
    df = pd.Series(agg).unstack(fill_value=0.0)
    df.index.name = "mes"
    return df.sort_index()


def meses_disponiveis(tx):
    return sorted({m for t in tx if (m := _mes(t.get("data")))})


# ───────────────────────── detecção de recorrentes ─────────────────────────
def _group_series(tx):
    """chave -> {label, categoria, escopo, serie:{mes: valor}}  (só despesas)."""
    groups = {}
    for t in tx:
        if not _is_despesa(t):
            continue
        m = _mes(t.get("data"))
        if not m:
            continue
        key = merchant_key(t.get("descricao"))
        chave = f"{t.get('escopo')}|{key}"
        g = groups.setdefault(chave, {
            "chave": chave, "label": _label(t.get("descricao")),
            "categoria": t.get("categoria"), "escopo": t.get("escopo"),
            "serie": defaultdict(float),
        })
        g["serie"][m] += float(t.get("saida") or 0)
    return groups


def detect_recurring(tx, min_meses=2, cv_fixo=0.15):
    """Lista de recorrentes detectados, ordenada por valor mensal (desc).

    Cada item: chave, label, categoria, escopo, meses (nº de meses vistos),
    valor (sugerido = mediana), tipo_rec ('fixo'|'recorrente'), cv, ativo=True.
    """
    n_meses_hist = len(meses_disponiveis(tx))
    out = []
    for g in _group_series(tx).values():
        serie = g["serie"]
        meses = len(serie)
        if meses < min_meses:
            continue
        vals = pd.Series(list(serie.values()), dtype=float)
        media = float(vals.mean())
        if media <= 0:
            continue
        cv = float(vals.std(ddof=0) / media) if media else 0.0
        out.append({
            "chave": g["chave"], "label": g["label"], "categoria": g["categoria"],
            "escopo": g["escopo"], "meses": meses,
            "valor": round(float(vals.median()), 2),
            "tipo_rec": "fixo" if cv <= cv_fixo else "recorrente",
            "cv": round(cv, 2),
            "cobertura": round(meses / n_meses_hist, 2) if n_meses_hist else 0.0,
            "ativo": True,
        })
    out.sort(key=lambda x: x["valor"], reverse=True)
    return out


def effective_recurring(detected, overrides):
    """Funde detectados com overrides do usuário (por chave) e itens manuais.

    overrides: dict chave -> {label, categoria, escopo, valor, ativo, origem}
    Retorna lista final de recorrentes efetivos (o que a projeção usa).
    """
    overrides = overrides or {}
    by_key = {d["chave"]: dict(d) for d in detected}
    for chave, ov in overrides.items():
        if chave in by_key:
            item = by_key[chave]
            item["valor"] = float(ov.get("valor", item["valor"]) or 0)
            item["ativo"] = bool(ov.get("ativo", 1))
            if ov.get("categoria"):
                item["categoria"] = ov["categoria"]
            if ov.get("label"):
                item["label"] = ov["label"]
        else:  # item criado manualmente pelo usuário
            by_key[chave] = {
                "chave": chave, "label": ov.get("label") or chave,
                "categoria": ov.get("categoria") or "A classificar",
                "escopo": ov.get("escopo") or "PF", "meses": 0,
                "valor": float(ov.get("valor") or 0), "tipo_rec": "fixo",
                "cv": 0.0, "cobertura": 0.0, "ativo": bool(ov.get("ativo", 1)),
                "origem": "manual",
            }
    return sorted(by_key.values(), key=lambda x: x["valor"], reverse=True)


# ───────────────────────── projeção ─────────────────────────
def _proximos_meses(ultimo_mes, n):
    ano, mes = int(ultimo_mes[:4]), int(ultimo_mes[5:7])
    out = []
    for _ in range(n):
        mes += 1
        if mes > 12:
            mes = 1; ano += 1
        out.append(f"{ano}-{mes:02d}")
    return out


def project(tx, recorrentes, months_ahead=3, growth=0.0, base_meses=3):
    """Projeta despesas dos próximos meses.

    Retorna dict com:
      historico: DataFrame mês -> {'despesa','recorrente','variavel','receita'}
      projecao:  DataFrame mês futuro -> {'fixo_recorrente','variavel','despesa_total',
                                          'receita','resultado'}
      por_categoria: DataFrame mês futuro -> despesa projetada por categoria
      resumo: dict com números-chave
    """
    meses = meses_disponiveis(tx)
    if not meses:
        return {"historico": pd.DataFrame(), "projecao": pd.DataFrame(),
                "por_categoria": pd.DataFrame(), "resumo": {}}

    ativos = [r for r in recorrentes if r.get("ativo")]
    chaves_ativas = {r["chave"] for r in ativos}
    fixo_total = sum(float(r["valor"]) for r in ativos)
    fixo_por_cat = defaultdict(float)
    for r in ativos:
        fixo_por_cat[r.get("categoria") or "Sem categoria"] += float(r["valor"])

    # despesa recorrente REAL por mês (para subtrair do baseline variável)
    groups = _group_series(tx)
    recorrente_mes = defaultdict(float)
    recorrente_mes_cat = defaultdict(lambda: defaultdict(float))
    for chave in chaves_ativas:
        g = groups.get(chave)
        if not g:
            continue
        cat = g["categoria"] or "Sem categoria"
        for m, v in g["serie"].items():
            recorrente_mes[m] += v
            recorrente_mes_cat[m][cat] += v

    desp = monthly_matrix(tx, "Despesa", "saida")
    rec = monthly_matrix(tx, "Receita", "entrada")
    desp_mes = desp.sum(axis=1) if not desp.empty else pd.Series(dtype=float)
    rec_mes = rec.sum(axis=1) if not rec.empty else pd.Series(dtype=float)

    hist = pd.DataFrame(index=meses)
    hist["despesa"] = [float(desp_mes.get(m, 0.0)) for m in meses]
    hist["recorrente"] = [float(recorrente_mes.get(m, 0.0)) for m in meses]
    hist["variavel"] = (hist["despesa"] - hist["recorrente"]).clip(lower=0)
    hist["receita"] = [float(rec_mes.get(m, 0.0)) for m in meses]
    hist.index.name = "mes"

    base = hist.tail(base_meses)
    var_baseline = float(base["variavel"].mean()) if len(base) else 0.0
    receita_baseline = float(base["receita"].mean()) if len(base) else 0.0

    # baseline variável por categoria (média recente do não-recorrente)
    var_cat_baseline = defaultdict(float)
    if not desp.empty:
        recent = desp.tail(base_meses)
        n = len(recent) or 1
        for cat in desp.columns:
            soma_var = 0.0
            for m in recent.index:
                soma_var += max(float(recent.at[m, cat]) - recorrente_mes_cat[m].get(cat, 0.0), 0.0)
            var_cat_baseline[cat] = soma_var / n

    futuros = _proximos_meses(meses[-1], months_ahead)
    proj_rows, cat_rows = [], []
    for i, m in enumerate(futuros, start=1):
        fator = (1 + growth) ** i
        var = var_baseline * fator
        despesa_total = fixo_total + var
        receita = receita_baseline
        proj_rows.append({
            "mes": m, "fixo_recorrente": round(fixo_total, 2), "variavel": round(var, 2),
            "despesa_total": round(despesa_total, 2), "receita": round(receita, 2),
            "resultado": round(receita - despesa_total, 2),
        })
        linha = {"mes": m}
        cats = set(fixo_por_cat) | set(var_cat_baseline)
        for cat in cats:
            linha[cat] = round(fixo_por_cat.get(cat, 0.0) + var_cat_baseline.get(cat, 0.0) * fator, 2)
        cat_rows.append(linha)

    projecao = pd.DataFrame(proj_rows).set_index("mes") if proj_rows else pd.DataFrame()
    por_cat = pd.DataFrame(cat_rows).set_index("mes") if cat_rows else pd.DataFrame()

    resumo = {
        "fixo_recorrente_mes": round(fixo_total, 2),
        "variavel_baseline_mes": round(var_baseline, 2),
        "despesa_projetada_mes": round(fixo_total + var_baseline, 2),
        "receita_baseline_mes": round(receita_baseline, 2),
        "resultado_projetado_mes": round(receita_baseline - fixo_total - var_baseline, 2),
        "n_recorrentes_ativos": len(ativos),
        "base_meses": min(base_meses, len(meses)),
    }
    return {"historico": hist, "projecao": projecao, "por_categoria": por_cat, "resumo": resumo}
