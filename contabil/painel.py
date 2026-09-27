# -*- coding: utf-8 -*-
"""
Painel bonito (as 5 telas aprovadas) renderizado DENTRO do Streamlit,
alimentado com os dados REAIS do histórico (Supabase/SQLite).

- Balanço Mensal e Análises usam os lançamentos reais.
- Planos, Investimentos e Contas a Pagar/Receber entram como "em breve"
  (dependem de cadastros que ainda vamos construir).

Uso:  st.components.v1.html(render(compute_dados(tx)), height=1500, scrolling=True)
"""
import json
from collections import defaultdict, OrderedDict
from datetime import date, datetime

NOMES_MES = {1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
             7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"}
ABR_MES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _mes(d):
    if isinstance(d, (date, datetime)):
        return f"{d.year}-{d.month:02d}"
    s = str(d or "")
    return s[:7] if len(s) >= 7 and s[4] == "-" else None


def compute_dados(tx):
    """Transforma os lançamentos reais no dicionário que o painel consome."""
    despesas = [t for t in tx if t.get("tipo") == "Despesa" and float(t.get("saida") or 0) > 0]
    receitas = [t for t in tx if t.get("tipo") == "Receita" and float(t.get("entrada") or 0) > 0]

    meses = sorted({m for t in tx if (m := _mes(t.get("data")))})
    if not meses:
        return {"temDados": False}
    meses12 = meses[-12:]
    mes_atual = meses[-1]
    ano_atual = int(mes_atual[:4])

    # fluxo mensal
    rec_por_mes = defaultdict(float)
    dep_por_mes = defaultdict(float)
    for t in receitas:
        m = _mes(t["data"])
        if m:
            rec_por_mes[m] += float(t["entrada"])
    for t in despesas:
        m = _mes(t["data"])
        if m:
            dep_por_mes[m] += float(t["saida"])

    fluxo = {
        "meses": [ABR_MES[int(m[5:7]) - 1] for m in meses12],
        "receita": [round(rec_por_mes.get(m, 0), 2) for m in meses12],
        "despesa": [round(dep_por_mes.get(m, 0), 2) for m in meses12],
    }

    # kpis do mês atual
    kpis = {"receita": round(rec_por_mes.get(mes_atual, 0), 2),
            "despesa": round(dep_por_mes.get(mes_atual, 0), 2)}
    kpis["saldo"] = round(kpis["receita"] - kpis["despesa"], 2)

    # ranking de despesas (ano todo)
    cat_total = defaultdict(float)
    for t in despesas:
        cat_total[t.get("categoria") or "Sem categoria"] += float(t["saida"])
    rank = sorted(cat_total.items(), key=lambda x: -x[1])[:12]
    rankDespesa = [{"nome": n, "valor": round(v, 2)} for n, v in rank]

    # % por categoria em relação à receita (mês atual)
    cat_mes = defaultdict(float)
    for t in despesas:
        if _mes(t["data"]) == mes_atual:
            cat_mes[t.get("categoria") or "Sem categoria"] += float(t["saida"])
    rec_mes = rec_por_mes.get(mes_atual, 0) or 1
    catPct = sorted(({"nome": n, "pct": round(v / rec_mes * 100, 1)} for n, v in cat_mes.items()),
                    key=lambda x: -x["pct"])[:8]

    # realizado x "normal" (média dos meses anteriores) — planejado provisório
    meses_ant = meses[:-1]
    realizadoPlanejado = []
    for n, real in sorted(cat_mes.items(), key=lambda x: -x[1])[:8]:
        soma = cont = 0.0
        for t in despesas:
            if (t.get("categoria") or "Sem categoria") == n and _mes(t["data"]) in meses_ant:
                soma += float(t["saida"])
        media = soma / len(meses_ant) if meses_ant else real
        realizadoPlanejado.append({"nome": n, "real": round(real, 2),
                                   "plan": round(media or real, 2)})

    # composição das receitas
    rec_cat = defaultdict(float)
    for t in receitas:
        rec_cat[t.get("categoria") or "Sem categoria"] += float(t["entrada"])
    tot_rec = sum(rec_cat.values()) or 1
    comp = sorted(rec_cat.items(), key=lambda x: -x[1])[:5]
    composicaoReceita = [{"nome": n, "pct": round(v / tot_rec * 100, 1)} for n, v in comp]

    # por ano
    ry = sum(float(t["entrada"]) for t in receitas if str(t.get("data", ""))[:4] == str(ano_atual))
    dy = sum(float(t["saida"]) for t in despesas if str(t.get("data", ""))[:4] == str(ano_atual))
    porAno = {"receita": round(ry, 2), "despesa": round(dy, 2), "saldo": round(ry - dy, 2)}

    # movimentação líquida por conta (proxy de saldo)
    fonte_net = defaultdict(float)
    for t in tx:
        fonte_net[t.get("fonte") or "Conta"] += float(t.get("entrada") or 0) - float(t.get("saida") or 0)
    saldoConta = sorted(({"nome": n, "valor": round(v, 2)} for n, v in fonte_net.items()),
                        key=lambda x: -abs(x["valor"]))[:6]

    # gasto por cartão (mês atual)
    cart = defaultdict(float)
    for t in despesas:
        f = t.get("fonte") or ""
        if "cart" in f.lower() and _mes(t["data"]) == mes_atual:
            cart[f] += float(t["saida"])
    cartoes = [{"nome": n, "gasto": round(v, 2)} for n, v in sorted(cart.items(), key=lambda x: -x[1])]

    # últimos lançamentos
    tx_ord = sorted([t for t in tx if t.get("data")], key=lambda t: str(t["data"]), reverse=True)[:6]
    ultimos = [{"data": str(t["data"])[8:10] + "/" + str(t["data"])[5:7],
                "desc": (t.get("descricao") or "")[:34], "escopo": t.get("escopo") or "",
                "cat": t.get("categoria") or "", "valor": round(float(t.get("entrada") or 0) - float(t.get("saida") or 0), 2)}
               for t in tx_ord]

    return {
        "temDados": True,
        "mesAtual": f"{NOMES_MES[int(mes_atual[5:7])]} {ano_atual}",
        "ano": ano_atual, "kpis": kpis, "fluxo": fluxo,
        "realizadoPlanejado": realizadoPlanejado, "catPct": catPct, "cartoes": cartoes,
        "rankDespesa": rankDespesa, "composicaoReceita": composicaoReceita,
        "porAno": porAno, "saldoConta": saldoConta, "ultimos": ultimos,
    }


def render(dados):
    return _HTML.replace("/*__DADOS__*/", json.dumps(dados, ensure_ascii=False))


_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap');
:root{--bg:#eef2f5;--surface:#fff;--surface-2:#f5f8fa;--ink:#1d2a31;--muted:#6a7a85;--border:#e7ecf0;--border-strong:#d8e0e5;
--teal:#1ba99b;--teal-2:#149487;--teal-soft:rgba(27,169,155,.16);--orange:#f0873c;--orange-2:#df7529;--orange-soft:rgba(240,135,60,.16);
--over:#e0544b;--violet:#8b5cf6;--r:15px;--shadow:0 1px 2px rgba(20,45,55,.04),0 10px 26px -16px rgba(20,45,55,.18)}
@media (prefers-color-scheme:dark){:root{--bg:#0d1316;--surface:#161e22;--surface-2:#121a1e;--ink:#e6eef1;--muted:#94a6af;--border:#242f35;--border-strong:#334047;
--teal:#33c3b5;--teal-2:#2bb0a3;--teal-soft:rgba(51,195,181,.15);--orange:#f5a15c;--orange-2:#ef8a3d;--orange-soft:rgba(245,161,92,.15);--over:#f0776b;--violet:#a68bf0;--shadow:0 1px 2px rgba(0,0,0,.3),0 12px 30px -16px rgba(0,0,0,.55)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;line-height:1.44}
h1,h2,h3{font-family:"Bricolage Grotesque","IBM Plex Sans",sans-serif;margin:0;letter-spacing:-.01em}
.app{display:grid;grid-template-columns:200px 1fr;min-height:100vh}
.side{background:var(--surface);border-right:1px solid var(--border);padding:14px 10px;display:flex;flex-direction:column;gap:4px}
.brand{display:flex;align-items:center;gap:9px;padding:6px 8px 12px}
.logo{width:32px;height:32px;border-radius:9px;background:linear-gradient(140deg,var(--teal),var(--teal-2));display:grid;place-items:center;color:#fff;font-family:"Bricolage Grotesque";font-weight:700;font-size:16px}
.brand b{font-family:"Bricolage Grotesque";font-size:14px}.brand small{display:block;color:var(--muted);font-size:11px}
.nav{border:0;background:none;font:inherit;text-align:left;display:flex;align-items:center;gap:9px;padding:8px 10px;border-radius:9px;color:var(--muted);font-size:13px;font-weight:500;cursor:pointer;width:100%}
.nav .ic{width:17px;text-align:center}.nav:hover{background:var(--surface-2);color:var(--ink)}
.nav.active{background:var(--teal-soft);color:var(--teal-2);font-weight:600}
.main{min-width:0;padding:18px 20px 40px}
.top{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.top h1{font-size:19px;margin-right:auto}
.pill{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:500;background:var(--surface);border:1px solid var(--border);border-radius:999px;padding:6px 12px;box-shadow:var(--shadow)}
.pill .dot{width:7px;height:7px;border-radius:50%;background:var(--teal)}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:14px 16px;box-shadow:var(--shadow);display:flex;align-items:center;gap:12px}
.kpi .ico{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;font-size:18px}
.kpi.r .ico,.kpi.s .ico{background:var(--teal-soft);color:var(--teal-2)}.kpi.d .ico{background:var(--orange-soft);color:var(--orange-2)}
.kpi .lbl{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;font-weight:600}
.kpi .val{font-family:"Bricolage Grotesque";font-weight:700;font-size:22px;margin-top:2px}
.kpi .val .c{font-size:12px;color:var(--muted);font-weight:600;margin-right:2px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:16px;box-shadow:var(--shadow);margin-bottom:12px}
.card .hd{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:10px}
.card h3{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;font-weight:600}
.card .hint{font-size:11px;color:var(--muted)}.card .big{font-family:"Bricolage Grotesque";font-weight:700;font-size:14px}
svg{display:block;width:100%;height:auto}.axis{fill:var(--muted);font-size:10px;font-family:"IBM Plex Mono",monospace}
.mlab{fill:var(--muted);font-size:9.5px;text-anchor:middle}.grid-line{stroke:var(--border)}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:6px;font-size:11.5px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}.legend i{width:10px;height:10px;border-radius:3px;display:inline-block}
.rp{display:flex;gap:14px;align-items:center}.rp .list{flex:1;display:flex;flex-direction:column;gap:8px;min-width:0}
.rp .row{display:grid;grid-template-columns:1fr auto;gap:2px 8px;align-items:center}
.rp .nm{font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rp .vv{font-size:11px;color:var(--muted);font-family:"IBM Plex Mono",monospace;text-align:right}
.rp .bar{grid-column:1/2;height:6px;border-radius:99px;background:var(--surface-2);border:1px solid var(--border);overflow:hidden}
.rp .bar i{display:block;height:100%;background:var(--orange);border-radius:99px}.rp .bar i.over{background:var(--over)}
.rp .pc{grid-column:2/3;font-size:10.5px;font-weight:600;color:var(--muted);text-align:right;font-family:"IBM Plex Mono",monospace}.rp .pc.over{color:var(--over)}
.donutwrap{flex:none;width:120px;text-align:center}.donutwrap .cap{font-size:10.5px;color:var(--muted);margin-top:2px}
.ranked{display:flex;flex-direction:column;gap:9px}.ranked .row{display:grid;grid-template-columns:120px 1fr auto;gap:9px;align-items:center}
.ranked .nm{font-size:12px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ranked .bar{height:18px;border-radius:5px;background:var(--surface-2);overflow:hidden}.ranked .bar i{display:block;height:100%;background:var(--orange);border-radius:5px}.ranked .bar i.t{background:var(--teal)}
.ranked .vv{font-size:11.5px;font-family:"IBM Plex Mono",monospace;font-weight:600;text-align:right;min-width:76px}
.tx .r{display:flex;align-items:center;gap:10px;padding:9px 2px;border-bottom:1px solid var(--border)}.tx .r:last-child{border:0}
.tx .av{width:30px;height:30px;border-radius:8px;display:grid;place-items:center;font-size:13px}.tx .av.in{background:var(--teal-soft);color:var(--teal-2)}.tx .av.out{background:var(--orange-soft);color:var(--orange-2)}
.tx .d{flex:1;min-width:0}.tx .d b{font-size:12.5px;font-weight:500;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tx .d small{font-size:11px;color:var(--muted)}
.tx .tg{font-size:10px;font-weight:600;color:var(--muted);background:var(--surface-2);border:1px solid var(--border);padding:2px 6px;border-radius:5px}
.tx .am{font-family:"IBM Plex Mono",monospace;font-weight:600;font-size:12.5px}.pos{color:var(--teal-2)}.neg{color:var(--orange-2)}
.soon{background:var(--surface);border:1px dashed var(--border-strong);border-radius:var(--r);padding:44px 20px;text-align:center;color:var(--muted)}
.soon b{color:var(--ink);font-family:"Bricolage Grotesque";font-size:17px}.soon p{max-width:440px;margin:8px auto 0;font-size:13px}
.view[hidden]{display:none}
.app{grid-template-columns:180px 1fr}
@media(max-width:640px){.app{grid-template-columns:1fr}.side{flex-direction:row;overflow-x:auto;border-right:0;border-bottom:1px solid var(--border)}.brand small{display:none}.nav{width:auto;white-space:nowrap}.kpis,.grid2{grid-template-columns:1fr}.rp{flex-direction:column-reverse;align-items:stretch}.donutwrap{width:100%}.ranked .row{grid-template-columns:100px 1fr auto}}
</style></head><body>
<div class="app">
  <aside class="side">
    <div class="brand"><div class="logo">Y</div><div><b>Youup Finanças</b><small>Iuri Henrique</small></div></div>
    <button class="nav active" data-view="dash"><span class="ic">📊</span>Balanço Mensal</button>
    <button class="nav" data-view="anal"><span class="ic">📈</span>Análises</button>
    <button class="nav" data-view="pend"><span class="ic">📅</span>Contas a Pagar/Receber</button>
    <button class="nav" data-view="planos"><span class="ic">🎯</span>Planos &amp; Metas</button>
    <button class="nav" data-view="inv"><span class="ic">💰</span>Investimentos</button>
  </aside>
  <main class="main">
    <div class="top"><h1 id="vtitle">Balanço Mensal</h1><span class="pill" id="pillmes"><span class="dot"></span>—</span></div>

    <section class="view" data-v="dash">
      <div class="kpis" id="kpis"></div>
      <div class="grid2">
        <div class="card"><div class="hd"><h3>Receitas e Despesas</h3><span class="hint" id="anoLbl"></span></div>
          <svg id="area" viewBox="0 0 560 240"></svg>
          <div class="legend"><span><i style="background:var(--teal)"></i>Receitas</span><span><i style="background:var(--orange)"></i>Despesas</span></div></div>
        <div class="card"><div class="hd"><h3>Gasto do mês × sua média</h3></div><div class="rp"><div class="list" id="rplist"></div>
          <div class="donutwrap"><svg id="donut" viewBox="0 0 130 130"></svg><div class="cap">do seu normal</div></div></div></div>
      </div>
      <div class="grid2">
        <div class="card"><div class="hd"><h3>% por categoria sobre a receita</h3><span class="hint">mês atual</span></div><svg id="catbars" viewBox="0 0 560 220"></svg></div>
        <div class="card"><div class="hd"><h3>Gasto por cartão</h3><span class="hint">mês atual</span></div><div class="ranked" id="cards"></div></div>
      </div>
    </section>

    <section class="view" data-v="anal" hidden>
      <div class="card"><div class="hd"><h3>Receitas e Despesas por mês</h3></div><svg id="anal-mes" viewBox="0 0 760 240"></svg>
        <div class="legend"><span><i style="background:var(--teal)"></i>Receitas</span><span><i style="background:var(--orange)"></i>Despesas</span></div></div>
      <div class="grid2">
        <div class="card"><div class="hd"><h3>Resumo de despesas</h3><span class="hint">ano</span></div><div class="ranked" id="rankdesp"></div></div>
        <div class="card"><div class="hd"><h3>Composição das receitas</h3></div><div class="rp"><div class="donutwrap" style="width:140px"><svg id="donutrec" viewBox="0 0 140 140"></svg></div><div class="list" id="reclegend" style="gap:10px"></div></div></div>
      </div>
      <div class="grid2">
        <div class="card"><div class="hd"><h3>Receitas × Despesas no ano</h3><span class="big" id="saldoAno"></span></div><svg id="anoBars" viewBox="0 0 400 190"></svg></div>
        <div class="card"><div class="hd"><h3>Movimentação por conta</h3></div><div class="ranked" id="saldoconta"></div></div>
      </div>
    </section>

    <section class="view" data-v="pend" hidden><div class="soon"><p style="font-size:32px;margin:0">📅</p><b>Contas a Pagar e a Receber</b><p>Precisa da coluna de <b>status</b> (pendente/concluído) nos lançamentos. Vamos ativar isso no próximo passo — aí seus vencimentos aparecem aqui automaticamente.</p></div></section>
    <section class="view" data-v="planos" hidden><div class="soon"><p style="font-size:32px;margin:0">🎯</p><b>Planos &amp; Metas</b><p>Aqui vão entrar suas metas (reserva, quitar financiamento, os 11 milhões). Precisa do cadastro de planos — próximo passo.</p></div></section>
    <section class="view" data-v="inv" hidden><div class="soon"><p style="font-size:32px;margin:0">💰</p><b>Investimentos</b><p>Seu patrimônio e o Grau de Independência Financeira rumo aos 11 mi. Precisa do cadastro de investimentos — próximo passo.</p></div></section>
  </main>
</div>
<script>
const DADOS=/*__DADOS__*/;
const SVG="http://www.w3.org/2000/svg",el=(t,a={})=>{const e=document.createElementNS(SVG,t);for(const k in a)e.setAttribute(k,a[k]);return e;};
const brl=v=>"R$ "+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:0,maximumFractionDigits:0});
const brl2=v=>Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
function donut(svg,cx,cy,r,sw,pct,color,big,small){const C=2*Math.PI*r,len=Math.min(pct,100)/100*C;
  svg.appendChild(el('circle',{cx,cy,r,fill:'none',stroke:'var(--surface-2)','stroke-width':sw}));
  svg.appendChild(el('circle',{cx,cy,r,fill:'none',stroke:color,'stroke-width':sw,'stroke-linecap':'round','stroke-dasharray':`${len} ${C-len}`,'stroke-dashoffset':C*0.25,transform:`rotate(-90 ${cx} ${cy})`}));
  if(big){const t=el('text',{x:cx,y:cy+(small?0:5),'text-anchor':'middle'});t.setAttribute('style','font-family:Bricolage Grotesque;font-weight:700;font-size:22px;fill:var(--ink)');t.textContent=big;svg.appendChild(t);}
  if(small){const t=el('text',{x:cx,y:cy+15,'text-anchor':'middle'});t.setAttribute('style','fill:var(--muted);font-size:9px');t.textContent=small;svg.appendChild(t);}}
function areaChart(id,arrR,arrD,labels,W,H){const s=document.getElementById(id);if(!s)return;s.innerHTML='';
  const ml=42,mr=12,mt=14,mb=26,pW=W-ml-mr,pH=H-mt-mb,n=labels.length||1;
  const yMax=Math.max(1,...arrR,...arrD)*1.12,step=niceStep(yMax);
  for(let g=0;g<=yMax;g+=step){const y=mt+pH-g/yMax*pH;s.appendChild(el('line',{class:'grid-line',x1:ml,y1:y,x2:W-mr,y2:y}));
    const t=el('text',{class:'axis',x:ml-6,y:y+4,'text-anchor':'end'});t.textContent=(g/1000)+'k';s.appendChild(t);}
  const X=i=>ml+(n<=1?pW/2:i*(pW/(n-1))),Y=v=>mt+pH-v/yMax*pH;
  const ap=a=>{let d=`M ${X(0)} ${mt+pH} `;a.forEach((v,i)=>d+=`L ${X(i)} ${Y(v)} `);return d+`L ${X(n-1)} ${mt+pH} Z`;};
  const lp=a=>{let d='';a.forEach((v,i)=>d+=(i?'L':'M')+` ${X(i)} ${Y(v)} `);return d;};
  s.appendChild(el('path',{d:ap(arrR),fill:'var(--teal-soft)'}));s.appendChild(el('path',{d:ap(arrD),fill:'var(--orange-soft)'}));
  s.appendChild(el('path',{d:lp(arrR),fill:'none',stroke:'var(--teal)','stroke-width':2.2,'stroke-linejoin':'round'}));
  s.appendChild(el('path',{d:lp(arrD),fill:'none',stroke:'var(--orange)','stroke-width':2.2,'stroke-linejoin':'round'}));
  labels.forEach((m,i)=>{const t=el('text',{class:'mlab',x:X(i),y:H-10});t.textContent=m;s.appendChild(t);});}
function barsChart(id,arrR,arrD,labels,W,H){const s=document.getElementById(id);if(!s)return;s.innerHTML='';
  const ml=42,mr=12,mt=14,mb=26,pW=W-ml-mr,pH=H-mt-mb,n=labels.length||1,colW=pW/n,bw=colW*0.30;
  const yMax=Math.max(1,...arrR,...arrD)*1.12,step=niceStep(yMax);
  for(let g=0;g<=yMax;g+=step){const y=mt+pH-g/yMax*pH;s.appendChild(el('line',{class:'grid-line',x1:ml,y1:y,x2:W-mr,y2:y}));
    const t=el('text',{class:'axis',x:ml-6,y:y+4,'text-anchor':'end'});t.textContent=(g/1000)+'k';s.appendChild(t);}
  for(let i=0;i<n;i++){const cx=ml+i*colW+colW/2,hr=arrR[i]/yMax*pH,hd=arrD[i]/yMax*pH;
    s.appendChild(el('rect',{x:cx-bw-1,y:mt+pH-hr,width:bw,height:hr,rx:3,fill:'var(--teal)'}));
    s.appendChild(el('rect',{x:cx+1,y:mt+pH-hd,width:bw,height:hd,rx:3,fill:'var(--orange)'}));
    const t=el('text',{class:'mlab',x:cx,y:H-10});t.textContent=labels[i];s.appendChild(t);}}
function niceStep(m){const raw=m/4,p=Math.pow(10,Math.floor(Math.log10(raw)));const n=raw/p;return (n>=5?5:n>=2?2:1)*p||1;}
function ranked(id,items,teal){const h=document.getElementById(id);if(!h)return;h.innerHTML='';const max=Math.max(1,...items.map(x=>Math.abs(x.valor)));
  items.forEach(x=>{const row=document.createElement('div');row.className='row';
    row.innerHTML=`<div class="nm">${x.nome}</div><div class="bar"><i class="${teal?'t':''}" style="width:${Math.round(Math.abs(x.valor)/max*100)}%"></i></div><div class="vv">${brl(x.valor)}</div>`;h.appendChild(row);});}

function build(){
  if(!DADOS.temDados){document.querySelector('.main').innerHTML='<div class="soon"><p style="font-size:32px;margin:0">📥</p><b>Sem dados ainda</b><p>Importe faturas/extratos (aba Importar, aqui embaixo) e clique em Salvar no histórico. Aí o painel ganha vida.</p></div>';return;}
  document.getElementById('pillmes').innerHTML='<span class="dot"></span>'+DADOS.mesAtual;
  document.getElementById('anoLbl').textContent=DADOS.ano;
  const k=DADOS.kpis,kc=document.getElementById('kpis');
  kc.innerHTML=`<div class="kpi r"><div class="ico">↘</div><div><div class="lbl">Receitas</div><div class="val"><span class="c">R$</span>${brl2(k.receita)}</div></div></div>
    <div class="kpi d"><div class="ico">↗</div><div><div class="lbl">Despesas</div><div class="val"><span class="c">R$</span>${brl2(k.despesa)}</div></div></div>
    <div class="kpi s"><div class="ico">${k.saldo>=0?'✓':'!'}</div><div><div class="lbl">Saldo do mês</div><div class="val ${k.saldo>=0?'pos':'neg'}"><span class="c">R$</span>${brl2(k.saldo)}</div></div></div>`;
  areaChart('area',DADOS.fluxo.receita,DADOS.fluxo.despesa,DADOS.fluxo.meses,560,240);
  // gasto x média
  const rl=document.getElementById('rplist');let tr=0,tp=0;
  DADOS.realizadoPlanejado.forEach(x=>{tr+=x.real;tp+=x.plan;const pc=x.plan>0?Math.round(x.real/x.plan*100):100,o=pc>110;
    const row=document.createElement('div');row.className='row';
    row.innerHTML=`<div class="nm">${x.nome}</div><div class="vv">${brl(x.real)}</div><div class="bar"><i class="${o?'over':''}" style="width:${Math.min(pc,100)}%"></i></div><div class="pc ${o?'over':''}">${pc}%</div>`;rl.appendChild(row);});
  const pct=tp>0?Math.round(tr/tp*100):100;donut(document.getElementById('donut'),65,65,48,15,pct,pct>110?'var(--over)':'var(--orange)',pct+'%','vs média');
  // % por categoria
  (function(){const s=document.getElementById('catbars'),cats=DADOS.catPct,W=560,H=220,ml=8,mr=8,mt=18,mb=52,pW=W-ml-mr,pH=H-mt-mb;
    const yMax=Math.max(1,...cats.map(c=>c.pct))*1.15,colW=pW/(cats.length||1),bw=Math.min(38,colW*0.5);
    cats.forEach((c,i)=>{const cx=ml+i*colW+colW/2,h=c.pct/yMax*pH,y=mt+pH-h;
      s.appendChild(el('rect',{x:cx-bw/2,y,width:bw,height:h,rx:5,fill:'var(--orange)'}));
      const t=el('text',{x:cx,y:y-5,'text-anchor':'middle'});t.setAttribute('style','fill:var(--ink);font-size:10.5px;font-weight:600;font-family:IBM Plex Mono');t.textContent=c.pct.toFixed(1).replace('.',',')+'%';s.appendChild(t);
      const l=el('text',{x:cx,y:mt+pH+15,'text-anchor':'end',transform:`rotate(-30 ${cx} ${mt+pH+15})`});l.setAttribute('class','mlab');l.textContent=(c.nome||'').slice(0,14);s.appendChild(l);});})();
  ranked('cards',DADOS.cartoes.length?DADOS.cartoes.map(c=>({nome:c.nome,valor:c.gasto})):[{nome:'Sem gasto em cartão no mês',valor:0}]);
  // análises
  barsChart('anal-mes',DADOS.fluxo.receita,DADOS.fluxo.despesa,DADOS.fluxo.meses,760,240);
  ranked('rankdesp',DADOS.rankDespesa);
  (function(){const cats=DADOS.composicaoReceita,cores=['var(--teal)','var(--teal-2)','var(--orange)','var(--violet)','var(--muted)'];
    const s=document.getElementById('donutrec'),cx=70,cy=70,r=50,C=2*Math.PI*r;let off=0;
    s.appendChild(el('circle',{cx,cy,r,fill:'none',stroke:'var(--surface-2)','stroke-width':17}));
    cats.forEach((c,i)=>{const len=c.pct/100*C;s.appendChild(el('circle',{cx,cy,r,fill:'none',stroke:cores[i%5],'stroke-width':17,'stroke-dasharray':`${len} ${C-len}`,'stroke-dashoffset':-off+C*0.25,transform:`rotate(-90 ${cx} ${cy})`}));off+=len;});
    if(cats[0]){const t=el('text',{x:cx,y:cy+5,'text-anchor':'middle'});t.setAttribute('style','font-family:Bricolage Grotesque;font-weight:700;font-size:16px;fill:var(--ink)');t.textContent=cats[0].pct.toFixed(0)+'%';s.appendChild(t);}
    const leg=document.getElementById('reclegend');cats.forEach((c,i)=>{const row=document.createElement('div');row.className='row';
      row.innerHTML=`<div class="nm"><span style="display:inline-block;width:9px;height:9px;border-radius:3px;background:${cores[i%5]};margin-right:6px"></span>${c.nome}</div><div class="vv">${c.pct.toFixed(1).replace('.',',')}%</div>`;leg.appendChild(row);});})();
  document.getElementById('saldoAno').textContent='Saldo '+brl(DADOS.porAno.saldo);
  (function(){const s=document.getElementById('anoBars'),W=400,H=190,mt=18,mb=28,pH=H-mt-mb,gx=W/2;
    const yMax=Math.max(1,DADOS.porAno.receita,DADOS.porAno.despesa)*1.15,Y=v=>mt+pH-v/yMax*pH;
    [[gx-70,DADOS.porAno.receita,'var(--teal)'],[gx+10,DADOS.porAno.despesa,'var(--orange)']].forEach(([x,v,c])=>{const h=v/yMax*pH;s.appendChild(el('rect',{x,y:Y(v),width:60,height:h,rx:6,fill:c}));
      const t=el('text',{x:x+30,y:Y(v)-7,'text-anchor':'middle'});t.setAttribute('style','fill:var(--ink);font-size:11px;font-weight:700;font-family:IBM Plex Mono');t.textContent=brl(v);s.appendChild(t);});
    [['Receitas',gx-40],['Despesas',gx+40]].forEach(([n,x])=>{const l=el('text',{x,y:H-9,'text-anchor':'middle'});l.setAttribute('class','mlab');l.textContent=n;s.appendChild(l);});})();
  ranked('saldoconta',DADOS.saldoConta,true);
}
document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.nav').forEach(x=>x.classList.remove('active'));b.classList.add('active');
  const v=b.dataset.view;document.querySelectorAll('.view').forEach(sec=>sec.hidden=(sec.dataset.v!==v));
  const titles={dash:'Balanço Mensal',anal:'Análises',pend:'Contas a Pagar e a Receber',planos:'Planos & Metas',inv:'Investimentos'};
  document.getElementById('vtitle').textContent=titles[v];}));
build();
</script></body></html>"""
