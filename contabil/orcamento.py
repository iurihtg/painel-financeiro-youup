# -*- coding: utf-8 -*-
"""
Planejamento orçamentário — metas de gasto por categoria/subcategoria.

É a tela "Planejamento e Controle" do estilo Meu Planner: você define um teto
planejado por categoria e o sistema mostra o **realizado × planejado** mês a mês,
marcando em vermelho onde estourou, com mín/médio/máximo dos últimos N meses para
ajudar a definir metas factíveis.

O orçamento fica em `settings["orcamento"]` = {categoria: valor_mensal}.
"""
import json
from collections import defaultdict, OrderedDict
from datetime import date, datetime

_ABR = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _mes(d):
    if isinstance(d, (date, datetime)):
        return f"{d.year}-{d.month:02d}"
    s = str(d or "")
    return s[:7] if len(s) >= 7 and s[4] == "-" else None


def _mes_abr(m):
    try:
        return f"{_ABR[int(m[5:7]) - 1]}/{m[2:4]}"
    except Exception:
        return m


def _split(cat):
    """'Grupo › Sub' ou 'Grupo/Sub' -> ('Grupo','Sub'); senão ('Categoria', None).
    Serve para o agrupamento AUTOMÁTICO (mãe/filha) a partir do nome da categoria."""
    c = str(cat or "").strip()
    for sep in ("›", ">", "/"):
        if sep in c:
            g, s = c.split(sep, 1)
            return g.strip(), s.strip()
    return c, None


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


# ═══════════════════════ planilha de planejamento (estilo Meu Planner) ═══════════════════════
def _agg(tx):
    """(tipo, categoria, mes) -> valor realizado."""
    agg = defaultdict(float)
    for t in tx:
        m = _mes(t.get("data"))
        if not m:
            continue
        if t.get("tipo") == "Despesa" and float(t.get("saida") or 0) > 0:
            agg[("Despesa", t.get("categoria") or "Sem categoria", m)] += float(t["saida"])
        elif t.get("tipo") == "Receita" and float(t.get("entrada") or 0) > 0:
            agg[("Receita", t.get("categoria") or "Sem categoria", m)] += float(t["entrada"])
    return agg


def _mmm(valores):
    """min/méd/máx dos meses COM gasto (ignora zeros); (0,0,0) se vazio."""
    v = [x for x in valores if x > 0]
    if not v:
        return 0.0, 0.0, 0.0
    return round(min(v), 2), round(sum(v) / len(v), 2), round(max(v), 2)


def _tipo_leaf(label, presentes):
    if label in presentes:
        return presentes[label]
    return "Receita" if "receita" in label.lower() else "Despesa"


def _grupo_de(cat, cat_grupo):
    """Grupo pai de uma categoria: pelo mapa cat_grupo, senão pelo prefixo 'Grupo › Sub',
    senão None (categoria avulsa/standalone)."""
    g = (cat_grupo or {}).get(cat)
    if g:
        return g.strip()
    gg, s = _split(cat)
    return gg if s else None


def montar_planejamento(tx, orcamento, cat_grupo=None, hoje=None, janela=3, n_meses=6,
                        extras=None):
    """Monta a planilha: seções Receitas/Despesas, grupos (categoria-mãe) com
    subcategorias, meses (realizado), mín/méd/máx da janela e uma lista `rows`
    achatada (com tipoLinha e chave) pronta para a tabela editável.

    cat_grupo: {categoria: grupo_pai}. extras: [{label,tipo}] categorias sem gasto.
    """
    hoje = hoje or date.today()
    orcamento = orcamento or {}
    cat_grupo = cat_grupo or {}
    agg = _agg(tx)
    meses_all = sorted({m for (_, _, m) in agg})
    mes_ref = f"{hoje.year}-{hoje.month:02d}"
    # n meses CONSECUTIVOS terminando no mês de referência (mesmo que algum esteja vazio)
    _y, _m = hoje.year, hoje.month
    meses_show = []
    for k in range(n_meses - 1, -1, -1):
        yy, mm = _y, _m - k
        while mm <= 0:
            mm += 12
            yy -= 1
        meses_show.append(f"{yy}-{mm:02d}")
    win = [m for m in meses_all if m <= mes_ref][-janela:]

    presentes = {}
    for (tp, cat, _m) in agg:
        presentes.setdefault(cat, tp)
    for e in (extras or []):
        presentes.setdefault(e["label"], e.get("tipo") or "Despesa")
    folhas = set(presentes) | set(orcamento)

    def realizado(cat, m):
        return round(agg.get(("Despesa", cat, m), 0.0) + agg.get(("Receita", cat, m), 0.0), 2)

    # mês de referência p/ o % (mais recente com dados)
    ref_m = win[-1] if win else (meses_all[-1] if meses_all else None)
    ref_idx = meses_show.index(ref_m) if ref_m in meses_show else None

    def _row(nome, cat, membros, tipoLinha):
        plan = round(sum(float(orcamento.get(c) or 0) for c in membros), 2)
        meses_v = []
        for m in meses_show:
            r = round(sum(realizado(c, m) for c in membros), 2)
            meses_v.append({"m": _mes_abr(m), "val": r, "over": (plan > 0 and r > plan)})
        mn, md, mx = _mmm([sum(realizado(c, m) for c in membros) for m in win])
        return {"nome": nome, "cat": cat, "plan": plan, "pct": 0.0,
                "min": mn, "med": md, "max": mx, "meses": meses_v, "tipoLinha": tipoLinha}

    def _secao(tipo):
        leaves = [c for c in folhas if _tipo_leaf(c, presentes) == tipo]
        # blocos: grupo (com folhas) ou folha avulsa
        grupos = OrderedDict()
        avulsas = []
        for leaf in leaves:
            g = _grupo_de(leaf, cat_grupo)
            if g:
                grupos.setdefault(g, []).append(leaf)
            else:
                avulsas.append(leaf)
        blocos = []
        for g, membros in grupos.items():
            blocos.append(("grupo", g, sorted(membros)))
        for leaf in avulsas:
            blocos.append(("avulsa", leaf, [leaf]))
        # ordena por gasto total desc
        def _tot(bloco):
            return sum(realizado(c, m) for c in bloco[2] for m in meses_show)
        blocos.sort(key=_tot, reverse=True)

        linhas = []
        for kind, nome, membros in blocos:
            if kind == "avulsa":
                r = _row(nome, nome, membros, "leaf")
                linhas.append(r)
            else:
                linhas.append(_row(nome, None, membros, "grupo"))
                for leaf in membros:
                    _g, s = _split(leaf)
                    sub_nome = s if s else leaf   # nome curto se veio 'Grupo › Sub'
                    linhas.append(_row(sub_nome, leaf, [leaf], "sub"))
        sec = _row(("Receitas" if tipo == "Receita" else "Despesas Mensais"), None, leaves, "sec")
        sec["linhas"] = linhas
        return sec

    receita = _secao("Receita")
    despesa = _secao("Despesa")

    # % = fatia da categoria no total REALIZADO da seção (qual categoria pesa mais
    # nas despesas/receitas), somando os meses exibidos. Independe de haver meta.
    def _fill_pct(sec):
        base = sum(m["val"] for m in sec["meses"])
        sec["pct"] = 100.0 if base > 0 else 0.0
        for r in sec["linhas"]:
            v = sum(m["val"] for m in r["meses"])
            r["pct"] = round(v / base * 100, 1) if base > 0 else 0.0
    _fill_pct(receita)
    _fill_pct(despesa)

    saldo = [round(receita["meses"][i]["val"] - despesa["meses"][i]["val"], 2)
             for i in range(len(meses_show))]

    # rows achatadas (saldo, seção receita + linhas, seção despesa + linhas)
    rows = []
    rows.append({"tipoLinha": "saldo", "nome": "Saldo Mensal (realizado)", "cat": None,
                 "plan": None, "pct": None, "min": None, "med": None, "max": None,
                 "meses": [{"val": v, "over": v < 0} for v in saldo]})
    for sec in (receita, despesa):
        rows.append({k: sec[k] for k in ("tipoLinha", "nome", "cat", "plan", "pct",
                                         "min", "med", "max", "meses")})
        rows.extend(sec["linhas"])

    return {
        "meses": [_mes_abr(m) for m in meses_show],
        "janela": janela, "nMeses": n_meses,
        "receita": receita, "despesa": despesa, "saldo": saldo,
        "rows": rows, "temDados": bool(agg) or bool(folhas),
    }


def render_planejamento(dados):
    return _GRID_HTML.replace("/*__DADOS__*/", json.dumps(dados, ensure_ascii=False))


_GRID_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
:root{--bg:#fff;--ink:#1d2a31;--muted:#6a7a85;--border:#e7ecf0;--gray:#f1f5f7;--teal:#1ba99b;--teal-d:#0f7f74;
--orange:#f0873c;--orange-d:#d06a24;--over:#d64533;--mono:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#161e22;--ink:#e6eef1;--muted:#94a6af;--border:#242f35;--gray:#1b242a;
--teal:#33c3b5;--teal-d:#2bb0a3;--orange:#f5a15c;--orange-d:#ef8a3d;--over:#f0776b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:12.5px}
.wrap{overflow-x:auto;border:1px solid var(--border);border-radius:12px}
table{border-collapse:collapse;width:100%;min-width:640px}
th,td{padding:6px 10px;border-bottom:1px solid var(--border);white-space:nowrap;text-align:right}
th{position:sticky;top:0;background:var(--bg);color:var(--muted);font-weight:600;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em;z-index:3}
th.cat,td.cat{text-align:left;position:sticky;left:0;background:var(--bg);z-index:2;min-width:190px}
th.cat{z-index:4}
td.num{font-family:var(--mono);font-variant-numeric:tabular-nums}
tr.sec td{font-weight:700;color:#fff;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em}
tr.sec.rec td{background:var(--teal)}tr.sec.rec td.cat{background:var(--teal)}
tr.sec.desp td{background:var(--orange)}tr.sec.desp td.cat{background:var(--orange)}
tr.grp td{background:var(--gray);font-weight:600}tr.grp td.cat{background:var(--gray)}
tr.sub td.cat{padding-left:26px;color:var(--muted);font-weight:400}
tr.tot td{font-weight:700;border-top:2px solid var(--border)}tr.tot td.cat{background:var(--bg)}
tr.saldo td{background:var(--gray);font-weight:700}tr.saldo td.cat{background:var(--gray)}
td.plan{font-weight:600}.over{color:var(--over);font-weight:700}
.muted{color:var(--muted)}.pct{color:var(--muted);font-size:11px}
.hint{color:var(--muted);font-size:11px;padding:8px 10px 0}
</style></head><body>
<div class="hint" id="hint"></div>
<div class="wrap"><table id="t"></table></div>
<script>
const D=/*__DADOS__*/;
const brl=v=>Number(v||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
function cellMeses(arr){return arr.map(x=>`<td class="num ${x.over?'over':''}">${x.val?brl(x.val):'<span class=muted>—</span>'}</td>`).join('');}
function build(){
  if(!D.temDados){document.getElementById('t').innerHTML='<tr><td class="cat">Sem lançamentos ainda — importe ou lance despesas.</td></tr>';fit();return;}
  const M=D.meses;
  let h='<thead><tr><th class="cat">Categorias e Subcategorias</th><th>Planejamento</th><th>%</th><th>Mín</th><th>Méd</th><th>Máx</th>';
  M.forEach(m=>h+=`<th>${m}</th>`);h+='</tr></thead><tbody>';
  // saldo mensal
  h+=`<tr class="saldo"><td class="cat">Saldo Mensal (realizado)</td><td></td><td></td><td></td><td></td><td></td>`;
  D.saldo.forEach(v=>h+=`<td class="num ${v<0?'over':''}">${brl(v)}</td>`);h+='</tr>';
  function secao(sec,titulo,cls){
    h+=`<tr class="sec ${cls}"><td class="cat">${titulo}</td><td class="num">${sec.plan?brl(sec.plan):''}</td><td>${sec.pct?sec.pct.toFixed(1).replace('.',',')+'%':''}</td><td class="num">${sec.min?brl(sec.min):''}</td><td class="num">${sec.med?brl(sec.med):''}</td><td class="num">${sec.max?brl(sec.max):''}</td>`;
    sec.meses.forEach(x=>h+=`<td class="num">${x.val?brl(x.val):''}</td>`);h+='</tr>';
    sec.linhas.forEach(r=>{
      h+=`<tr class="${r.tipoLinha}"><td class="cat">${r.nome}</td>`;
      h+=`<td class="num plan">${r.plan?brl(r.plan):'<span class=muted>—</span>'}</td>`;
      h+=`<td class="pct">${r.pct?r.pct.toFixed(1).replace('.',',')+'%':''}</td>`;
      h+=`<td class="num muted">${r.min?brl(r.min):''}</td><td class="num">${r.med?brl(r.med):''}</td><td class="num muted">${r.max?brl(r.max):''}</td>`;
      h+=cellMeses(r.meses)+'</tr>';
    });
  }
  secao(D.receita,'▸ Receitas','rec');
  secao(D.despesa,'▸ Despesas Mensais','desp');
  h+='</tbody>';
  document.getElementById('t').innerHTML=h;
  document.getElementById('hint').innerHTML=`Mín/Méd/Máx dos últimos <b>${D.janela}</b> meses (só meses com gasto). Vermelho = passou do planejado no mês. Role a tabela para o lado para ver mais meses →`;
  fit();
}
function fit(){const b=document.body,h=Math.ceil(b.getBoundingClientRect().height)+8;
  try{if(window.frameElement)window.frameElement.style.height=h+'px';}catch(e){}
  try{parent.postMessage({type:'streamlit:setFrameHeight',height:h},'*');}catch(e){}}
build();window.addEventListener('load',fit);setTimeout(fit,300);setTimeout(fit,900);
try{new ResizeObserver(fit).observe(document.body);}catch(e){}
</script></body></html>"""
