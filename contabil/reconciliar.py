# -*- coding: utf-8 -*-
"""
Motor anti-duplicação — o "cérebro" da Fase 2.

Objetivo (pedido do Iuri): **impedir que o mesmo dinheiro seja contado duas
vezes**. O caso clássico:

    recebe na maquininha (PJ)  →  transfere PJ→PF  →  paga contas (PF)

Isso é UM fluxo de dinheiro, não três. A venda na maquininha é a receita real;
a transferência PJ→PF e o crédito que chega na conta PF são movimentos internos
— não são nova receita nem nova despesa.

Como funciona:
  - `detectar` varre o histórico e devolve *suspeitas* de duplicação, com motivo
    e confiança. NÃO altera nada sozinho — dinheiro é sério, quem confirma é o
    Iuri (na aba 🔁 Duplicações).
  - Ao confirmar, o app "neutraliza" as pernas internas: muda o `tipo` para
    `TIPO_INTERNO`, que o painel já ignora nos totais de receita/despesa (mas
    mantém o registro e o efeito no saldo por conta — o dinheiro realmente
    andou entre as contas).
  - Decisões (confirmar/ignorar) ficam salvas em `dedup_resolvidos`, então o
    mesmo par não volta a incomodar.

Dois padrões detectados:
  A) TRANSFERÊNCIA INTERNA — uma saída de uma conta que "reaparece" como
     entrada em outra (mesmo valor, poucos dias de diferença). É o coração do
     pedido do Iuri.
  B) DUPLICATA — o mesmo lançamento contado duas vezes (ex.: digitou à mão e
     depois importou o extrato).
"""
import re
import unicodedata
from datetime import date, datetime

# tipo dado às pernas neutralizadas — o painel NÃO conta isso em receita/despesa
TIPO_INTERNO = "Transferência entre contas próprias"

# pistas de que um lançamento é uma transferência / liquidação interna
_PISTAS = [
    "transfer", "transferencia", "pix", "ted", "doc ", "tef", "liberacao",
    "liberado", "saldo", "moderninha", "maquininha", "pagbank", "adquir",
    "youup", "iuri", "resgate", "aplicacao", "aplic", "entre contas", "p2p",
    "saque", "deposito",
]


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def _data(t):
    s = str(t.get("data") or "")[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _valor(t):
    """Valor absoluto do lançamento (entrada OU saída)."""
    return round(float(t.get("entrada") or 0) - float(t.get("saida") or 0), 2)


def _conta(t):
    return f"{t.get('escopo') or ''} · {t.get('fonte') or 'Conta'}"


def _tem_pista(t):
    d = _norm(t.get("descricao")) + " " + _norm(t.get("categoria"))
    return any(p in d for p in _PISTAS)


def _eh_receita_primaria(t):
    """Venda na maquininha / faturamento real: é receita de verdade, NUNCA a
    perna de chegada de uma transferência. Não pode ser neutralizada."""
    d = _norm(t.get("descricao")) + " " + _norm(t.get("categoria"))
    return any(k in d for k in ("venda pela moderninha", "vendas (maquininha)",
                                "venda ", "vendas", "faturamento", "honorario",
                                "receita - vendas"))


def assinatura(ids):
    """Chave estável de uma suspeita (independe da ordem dos ids)."""
    return "|".join(sorted(str(i) for i in ids))


def _conta_no_total(t):
    """Só lançamentos que HOJE entram nos totais podem gerar dupla contagem."""
    return t.get("tipo") in ("Receita", "Despesa")


def detectar(tx, resolvidos=None, janela_dias=4, tol_pct=0.03):
    """Devolve lista de suspeitas de duplicação ainda não resolvidas.

    tx         : list[dict] (store.load_transactions())
    resolvidos : dict {assinatura: "neutralizado"|"ignorado"} — o que o Iuri já decidiu
    janela_dias: quantos dias entre as duas pernas de uma transferência
    tol_pct    : tolerância de valor (pega taxa de maquininha/tarifa)
    """
    resolvidos = resolvidos or {}
    contam = [t for t in tx if _conta_no_total(t) and t.get("id")]
    suspeitas = []

    # ── A) transferência interna: saída numa conta ↔ entrada em outra ──
    saidas = [t for t in contam if float(t.get("saida") or 0) > 0]
    entradas = [t for t in contam if float(t.get("entrada") or 0) > 0]
    usados = set()
    for o in saidas:
        vo = float(o.get("saida") or 0)
        do = _data(o)
        if not do or vo <= 0:
            continue
        melhor = None
        for i in entradas:
            if i["id"] in usados or i["id"] == o["id"]:
                continue
            # tem que ser conta diferente (senão não é transferência entre contas)
            if _conta(i) == _conta(o):
                continue
            # a chegada de uma transferência NÃO pode ser antes da saída,
            # e uma venda/faturamento real nunca é "perna de chegada"
            di = _data(i)
            if not di:
                continue
            dias = (di - do).days
            if dias < 0 or dias > janela_dias:
                continue
            if _eh_receita_primaria(i):
                continue
            vi = float(i.get("entrada") or 0)
            diff = abs(vi - vo)
            tol = max(0.02, vo * tol_pct)
            if diff > tol:
                continue
            # precisa cheirar a transferência: ou tem pista, ou cruza PF↔PJ
            cruza_escopo = (o.get("escopo") != i.get("escopo"))
            if not (_tem_pista(o) or _tem_pista(i) or cruza_escopo):
                continue
            # prioriza: cruza PF↔PJ > menos dias > valor mais próximo
            score = (0 if cruza_escopo else 1, dias, diff)
            if melhor is None or score < melhor[0]:
                melhor = (score, i)
        if melhor:
            i = melhor[1]
            sig = assinatura([o["id"], i["id"]])
            if sig in resolvidos:
                usados.add(i["id"])
                continue
            usados.add(i["id"])
            exato = abs(float(i.get("entrada") or 0) - vo) <= max(0.02, vo * 0.001)
            cruza = o.get("escopo") != i.get("escopo")
            motivo = ("Saiu de uma conta e entrou em outra com o mesmo valor "
                      f"em {abs((_data(i) - _data(o)).days)} dia(s)")
            if cruza:
                motivo += f" — cruza {o.get('escopo')}→{i.get('escopo')} (ex.: maquininha → conta pessoal)"
            suspeitas.append({
                "kind": "transferencia",
                "sig": sig,
                "confianca": "alta" if exato else "média",
                "motivo": motivo,
                "ids": [o["id"], i["id"]],
                "acao": "neutralizar",
                "legs": [_leg(o, "saída"), _leg(i, "entrada")],
                "valor": round(vo, 2),
            })

    # ── B) duplicata exata: mesmo evento contado 2x ──
    grupos = {}
    for t in contam:
        d = _data(t)
        if not d:
            continue
        chave = (d, t.get("escopo"), t.get("fonte"), round(abs(_valor(t)), 2),
                 "e" if float(t.get("entrada") or 0) > 0 else "s")
        grupos.setdefault(chave, []).append(t)
    for chave, grp in grupos.items():
        if len(grp) < 2:
            continue
        # descrições parecidas o suficiente (mesma conta+dia+valor já é forte)
        grp = sorted(grp, key=lambda t: str(t.get("id")))
        ids = [t["id"] for t in grp]
        sig = assinatura(ids)
        if sig in resolvidos:
            continue
        suspeitas.append({
            "kind": "duplicata",
            "sig": sig,
            "confianca": "alta",
            "motivo": f"{len(grp)} lançamentos idênticos (mesmo dia, conta e valor) — "
                      "provável digitação + importação do mesmo item",
            "ids": ids,
            "acao": "excluir_extras",
            "legs": [_leg(t, "entrada" if float(t.get("entrada") or 0) > 0 else "saída") for t in grp],
            "valor": round(abs(_valor(grp[0])), 2),
        })

    # mais confiáveis e mais recentes primeiro
    ordem = {"alta": 0, "média": 1}
    suspeitas.sort(key=lambda s: (ordem.get(s["confianca"], 2),
                                  -max((_data_ord(x) for x in s["legs"]), default=0)))
    return suspeitas


def _data_ord(leg):
    s = str(leg.get("data") or "")[:10].replace("-", "")
    return int(s) if s.isdigit() else 0


def _leg(t, direcao):
    return {
        "id": t["id"], "data": str(t.get("data") or "")[:10], "direcao": direcao,
        "conta": _conta(t), "escopo": t.get("escopo"), "fonte": t.get("fonte"),
        "descricao": (t.get("descricao") or "")[:60], "categoria": t.get("categoria"),
        "valor": round(abs(_valor(t)), 2),
    }


def resumo(suspeitas):
    """Texto curto para alertar o Iuri."""
    if not suspeitas:
        return None
    n_t = sum(1 for s in suspeitas if s["kind"] == "transferencia")
    n_d = sum(1 for s in suspeitas if s["kind"] == "duplicata")
    partes = []
    if n_t:
        partes.append(f"{n_t} transferência(s) interna(s)")
    if n_d:
        partes.append(f"{n_d} duplicata(s)")
    return " e ".join(partes) + " podem estar inflando seus números."
