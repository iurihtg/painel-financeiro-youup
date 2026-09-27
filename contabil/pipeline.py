# -*- coding: utf-8 -*-
"""
Pipeline de consolidação de faturas/extratos -> lançamentos normalizados.

Fluxo: process(paths) -> (tx, report)
  1. deduplica arquivos por conteúdo (evita PDFs repetidos)
  2. detecta a origem de cada arquivo pelo conteúdo (não pelo nome)
  3. faz o parsing de cada origem em lançamentos normalizados
  4. reclassifica pagamentos de fatura entre fontes (evita dupla contagem)

Cada lançamento é um dict:
  data (date), escopo ('PF'|'PJ'), fonte (str), descricao (str),
  entrada (float), saida (float), tipo (str), categoria (str), obs (str)
"""
import os, re, shutil, subprocess, hashlib, unicodedata
from datetime import datetime, date
from collections import defaultdict

import openpyxl

# ───────────────────────── helpers ─────────────────────────
def brl(s):
    """'-R$ 1.234,56' / '1.483,49' / '-134,60' -> float (ou None)."""
    if s is None:
        return None
    s = str(s).replace("R$", "").replace("\xa0", " ").strip()
    neg = s.startswith("-") or s.startswith("(")
    s = s.replace("-", "").replace("+", "").replace("(", "").replace(")", "").strip()
    s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def norm(t):
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def pdf_text(path, layout=True):
    """Extrai texto de PDF. Usa pdftotext (poppler) se existir; senão pdfplumber."""
    if shutil.which("pdftotext"):
        args = ["pdftotext", "-layout" if layout else "-raw", path, "-"]
        return subprocess.run(args, capture_output=True, text=True).stdout
    import pdfplumber  # fallback puro-python
    out = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            out.append(pg.extract_text(layout=layout) or "")
    return "\n".join(out)


MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4, "maio": 5,
         "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
         "novembro": 11, "dezembro": 12}
MES_ABR = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8}
ANO_PADRAO = 2026  # ano-base do relatório

# ───────────────────────── categorização ─────────────────────────
CAT_RULES = [
    ("Transferência PF↔PJ (Youup)", ["youup"]),
    ("Adquirência (taxas maquininha)", ["taxa de intermediacao", "taxa de parcelamento", "taxa de servico"]),
    ("Receita - Vendas (maquininha)", ["venda pela moderninha"]),
    ("Receita - Pix/transferência", ["pix recebid", "transf pix recebida", "pagamento de pix do pagbank",
                                      "pix transf youup", "sispag pix", "ted ", "dep din", "deposito"]),
    ("Rendimentos/Investimentos", ["rend pago aplic", "aplic aut", "investiment"]),
    ("Impostos/Tributos", ["darf", "rec fed", "receita fed", "das mei", "das ", "fgts", "inss"]),
    ("Tarifas e juros bancários", ["juros limite", "juros do", "juros de mora", "multa por atraso",
                                   "encargos de atraso", "juros de financiamento", "iof", "tarifa",
                                   "anuidade", "mensalidade cartao", "juros excesso"]),
    ("Financiamento (veículo)", ["financ veic", "pagto financ veic", "byd do brasil"]),
    ("Financiamento/Habitação", ["gci caixa", "caixa - habitacao", "habitacao", "cartoes caixa", "cartao caixa"]),
    ("Empréstimo/Crédito", ["banco bv", "banco itau", "banco itaú"]),
    ("Seguros", ["sul america", "sulamerica", "seguro"]),
    ("Energia elétrica", ["energisa"]),
    ("Água/Saneamento", ["igua sergip", "igua ", "deso"]),
    ("Telefonia/Internet", ["vivo-se", "vivo ", "claro", "tim ", "oi ", "internet"]),
    ("Moradia/Condomínio", ["alphaville", "condominio", "pyreneus", "pirenopolis", "gav pirenopolis",
                            "villa veron", "residence", "loctal locacoes"]),
    ("Combustível", ["combust", "rede rpb", "posto", "ipiranga", "shell"]),
    ("Supermercado", ["supermerc", "mini mercado", "m melo", "mmelo", "1minuto", "star max", "bombom",
                      "mercado oliveira", "emporio", "ns distribuidora"]),
    ("Alimentação/Restaurante", ["ifood", "minhoburguer", "rei do acaraje", "restaurante", "do bibi",
                                 "adega", "pizzaria", "zapizi", "sorveteria", "acaraje"]),
    ("Saúde/Farmácia", ["farmacia", "drogas", "raia", "supramed", "material medico", "laborat",
                        "dap produtos", "hospital", "clinica"]),
    ("Educação/Cursos", ["edzmentoria", "mentoria", "kiwify", "hotmart", "executive marketing", "uncpay", "curso"]),
    ("Doações", ["arquidiocese", "paroquia", "diocese", "doacao", "doacoes"]),
    ("Marketing", ["facebk", "facebook", "google ads", "greatpages", "mlabs"]),
    ("Assinaturas/Serviços digitais", ["apple.com", "applecombill", "google", "netflix", "spotify",
                                       "mercadolivre", "mercado livre", "mercadopago", "mercado pago",
                                       "pagar me", "pagar.me", "urentcar", "jetshr", "pepe coin",
                                       "uber do bra", "anthropic", "obsidian", "zupper", "openai",
                                       "chatgpt", "adobe", "microsoft", "speedfy", "asaas"]),
    ("Software/Cursos/Comunidades", ["asimov", "htm*", "perpetuo club", "buzzcrush"]),
    ("Compras/E-commerce", ["shopee", "amazon", "aliexpress", "magalu", "americanas", "shein"]),
    ("Transporte/Viagens", ["uber", "99app", "99 ", "sao jose", "transporte", "maxmilhas",
                            "latam", "gol ", "azul ", "passagem"]),
    ("Cuidados pessoais", ["orion", "salao", "barbearia", "cuidados"]),
    ("Vestuário/Compras", ["riachuelo", "renner", "centro autom", "casa das tintas", "centerplex",
                           "shop scp", "aracaju adm shop", "mulvi", "material de constr"]),
]

def categorizar(desc, tipo="Despesa"):
    d = norm(desc)
    for cat, keys in CAT_RULES:
        if any(k in d for k in keys):
            return cat
    if tipo in ("Transferência entre contas próprias", "Pagamento de fatura de cartão", "Estorno/Devolução"):
        return tipo
    return "A classificar"

# lista de categorias-padrão para a aba Listas / dropdown
DEFAULT_CATEGORIES = sorted({c for c, _ in CAT_RULES} | {
    "A classificar", "Estorno/Devolução", "Pagamento de fatura de cartão",
    "Transferência entre contas próprias", "Liquidação/transferência interna",
    "Transferência/Pix a terceiros", "Compras diversas/avulsas",
    "Saldo transportado (memo)", "Pagamento fatura cartão Cora (PJ, sem detalhamento)",
})

OWN = ["iuri h", "iuri henrique", "iuri he", "iurihe", "iuri teixeira"]
def is_own(desc):
    d = norm(desc)
    return any(o in d for o in OWN)

def _tx(data, escopo, fonte, descricao, entrada, saida, tipo, categoria, obs=""):
    return dict(data=data, escopo=escopo, fonte=fonte, descricao=descricao,
                entrada=round(entrada or 0.0, 2), saida=round(saida or 0.0, 2),
                tipo=tipo, categoria=categoria, obs=obs)

# ───────────────────────── detecção de origem ─────────────────────────
def detect_source(path):
    """Retorna um tag de origem a partir do CONTEÚDO do arquivo."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".ofx":
        return "ofx"
    if ext in (".xlsx", ".xlsm"):
        try:
            wb = openpyxl.load_workbook(path, data_only=True)
        except Exception:
            return None
        sheets = [s.upper() for s in wb.sheetnames]
        if set(sheets) & set(MES_ABR) and len(set(sheets) - set(MES_ABR)) == 0:
            return "btg_card"
        ws = wb.active
        mr=min(ws.max_row or 1, 12); mc=min(ws.max_column or 1, 10)
        blob = " ".join(str(ws.cell(r, c).value) for r in range(1, mr + 1)
                        for c in range(1, mc + 1) if ws.cell(r, c).value)
        b = norm(blob)
        if "final 6434" in b:
            return "itau_card_6434"
        if "final 4482" in b:
            return "itau_card_4482"
        if "lancamento" in b and "titularidade" in b:
            return "itau_card_6434"  # cartão Itaú genérico; nº é lido depois
        # planilha-modelo (Data/Descrição/Valor) — importação universal
        for r in range(1, min(ws.max_row or 1, 8) + 1):
            hdr = {norm(ws.cell(r, c).value) for c in range(1, (ws.max_column or 1) + 1)
                   if ws.cell(r, c).value is not None}
            if {"data", "descricao", "valor"} <= hdr:
                return "excel_modelo"
        return None
    if ext == ".pdf":
        t = norm(pdf_text(path, layout=True))
        # 1) extratos de conta — cabeçalhos fortes (checar antes dos cartões,
        #    pois extratos contêm transações "cartões caixa"/"mercado pago"/"fatura cora")
        if "btg pactual" in t and "extrato de conta corrente" in t:
            return "btg_account"
        if "personnalite" in t and "extrato conta corrente" in t:
            return "itau_account"
        if "cora" in t and "saldo do dia" in t:
            return "cora_account"
        # 2) faturas de cartão — marcadores específicos de fatura
        if "cora sociedade de credito" in t and "total de compras" in t:
            return "cora_card"
        if "cartoes caixa" in t and "valor total desta fatura" in t:
            return "caixa_card"
        if "mercado pago" in t and ("essa e sua fatura" in t or "detalhes de consumo" in t):
            return "mp_card"
        if ("pagbank" in t or "pagseguro" in t) and "extrato financeiro" in t:
            return "pagbank"
    return None

# ───────────────────────── parsers ─────────────────────────
def parse_itau_card(path, numero):
    fonte = f"Cartão Itaú final {numero}"
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    inv = ws.title
    hdr = next((r for r in range(1, ws.max_row + 1)
                if ws.cell(r, 2).value == "Data" and ws.cell(r, 3).value == "Lançamento"), None)
    if hdr is None:
        return []
    rows = []
    for r in range(hdr + 1, ws.max_row + 1):
        dt, desc, parc, val = (ws.cell(r, c).value for c in (2, 3, 4, 5))
        if dt is None or desc is None or val is None:
            continue
        if isinstance(dt, datetime):
            dt = dt.date()
        desc = str(desc).strip()
        obs = inv + (f" | {parc}" if parc else "")
        nd = norm(desc)
        if val < 0 and nd.startswith("pagamento"):
            rows.append(_tx(dt, "PF", fonte, desc, abs(val), 0, "Pagamento de fatura de cartão",
                            "Pagamento de fatura de cartão", obs))
        elif val < 0 or "estorno" in nd:
            rows.append(_tx(dt, "PF", fonte, desc, abs(val), 0, "Estorno/Devolução", "Estorno/Devolução", obs))
        else:
            rows.append(_tx(dt, "PF", fonte, desc, 0, val, "Despesa", categorizar(desc), obs))
    return rows


def parse_btg_card(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    datep = re.compile(r"^(\d{1,2}) De (\w+)", re.I)
    rows = []
    for sh in wb.sheetnames:
        ws = wb[sh]
        cur_mon = MES_ABR.get(sh.upper())
        cur_day = None
        seq = [ws.cell(r, 1).value for r in range(1, ws.max_row + 1)
               if ws.cell(r, 1).value is not None and str(ws.cell(r, 1).value).strip() != ""]
        j = 0
        while j < len(seq):
            s = str(seq[j]).strip()
            m = datep.match(s)
            if m:
                cur_day = int(m.group(1))
                mm = MESES.get(norm(m.group(2)))
                if mm:
                    cur_mon = mm
                j += 1
                continue
            if s == "undefined":
                name = seq[j + 1] if j + 1 < len(seq) else None
                typ = seq[j + 2] if j + 2 < len(seq) else None
                val = next((seq[k] for k in range(j + 1, min(j + 5, len(seq)))
                            if isinstance(seq[k], (int, float))), None)
                if val is not None and cur_day and cur_mon:
                    # ano: compra em mês posterior ao da fatura => ano anterior
                    ano = ANO_PADRAO - 1 if (MES_ABR.get(sh.upper()) and cur_mon > MES_ABR[sh.upper()]) else ANO_PADRAO
                    try:
                        dt = date(ano, cur_mon, cur_day)
                    except ValueError:
                        dt = None
                    desc = str(name).strip() if name else ""
                    typ_s = str(typ).strip() if typ else ""
                    nd = norm(f"{typ_s} {desc}")
                    obs = f"{sh} | {typ_s}"
                    if "pagamento de fatura" in nd:
                        rows.append(_tx(dt, "PF", "Cartão BTG", desc or typ_s, abs(val), 0,
                                        "Pagamento de fatura de cartão", "Pagamento de fatura de cartão", obs))
                    elif val < 0:
                        rows.append(_tx(dt, "PF", "Cartão BTG", desc or typ_s, 0, abs(val), "Despesa",
                                        categorizar(desc or typ_s), obs))
                    else:
                        rows.append(_tx(dt, "PF", "Cartão BTG", desc or typ_s, val, 0,
                                        "Estorno/Devolução", "Estorno/Devolução", obs))
                j += 1
                continue
            j += 1
    return rows


def parse_btg_account(text):
    lre = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s+\d{2}h\d{2}\s+(.*?)\s+(-?R\$\s[\d.,]+)\s*$")
    rows = []
    for ln in text.splitlines():
        m = lre.match(ln)
        if not m:
            continue
        if "Saldo Diário" in m.group(2) or "Saldo Diario" in m.group(2):
            continue
        dt = datetime.strptime(m.group(1), "%d/%m/%Y").date()
        val = brl(m.group(3))
        parts = re.split(r"\s{2,}", m.group(2).strip())
        if len(parts) >= 3:
            cat_bank, trans, desc = parts[0], parts[1], " ".join(parts[2:])
        elif len(parts) == 2:
            cat_bank, trans, desc = "", parts[0], parts[1]
        else:
            cat_bank, trans, desc = "", "", parts[0]
        full = f"{trans} {desc}".strip()
        nd = norm(f"{trans} {desc}")
        obs = f"BTG conta | {cat_bank} {trans}".strip()
        if "pagamento de fatura do cartao" in nd or ("fatura" in nd and "cartao" in nd):
            rows.append(_tx(dt, "PF", "BTG conta corrente", full, abs(val) if val < 0 else 0, 0,
                            "Pagamento de fatura de cartão", "Pagamento de fatura de cartão", obs))
        elif is_own(desc) and ("pix" in nd or "transf" in nd):
            rows.append(_tx(dt, "PF", "BTG conta corrente", full, val if val > 0 else 0,
                            abs(val) if val < 0 else 0, "Transferência entre contas próprias",
                            "Transferência entre contas próprias", obs))
        elif val is not None and val < 0:
            rows.append(_tx(dt, "PF", "BTG conta corrente", full, 0, abs(val), "Despesa",
                            categorizar(desc or trans), obs))
        else:
            rows.append(_tx(dt, "PF", "BTG conta corrente", full, val or 0, 0, "Receita",
                            categorizar(desc or trans, "Receita"), obs))
    return rows


def parse_itau_account(text):
    ire = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s+(.*?)\s+(-?[\d.]+,\d{2})\s*$")
    rows = []
    for ln in text.splitlines():
        m = ire.match(ln)
        if not m:
            continue
        desc = m.group(2).strip()
        nd = norm(desc)
        if nd.startswith("saldo") or "saldo total dispon" in nd or "saldo anterior" in nd:
            continue
        dt = datetime.strptime(m.group(1), "%d/%m/%Y").date()
        val = brl(m.group(3))
        obs = "Itaú conta"
        if any(k in nd for k in ["pers black", "fatura paga personnalite", "faturaitau", "fatura itau",
                                 "cartao personnalite", "pgto min-itaucard", "fatura person"]):
            rows.append(_tx(dt, "PF", "Itaú conta corrente", desc, abs(val) if val < 0 else 0, 0,
                            "Pagamento de fatura de cartão", "Pagamento de fatura de cartão", obs))
        elif is_own(desc) and ("pix" in nd or "transf" in nd):
            rows.append(_tx(dt, "PF", "Itaú conta corrente", desc, val if val > 0 else 0,
                            abs(val) if val < 0 else 0, "Transferência entre contas próprias",
                            "Transferência entre contas próprias", obs))
        elif val is not None and val < 0:
            rows.append(_tx(dt, "PF", "Itaú conta corrente", desc, 0, abs(val), "Despesa", categorizar(desc), obs))
        else:
            rows.append(_tx(dt, "PF", "Itaú conta corrente", desc, val or 0, 0, "Receita",
                            categorizar(desc, "Receita"), obs))
    return rows


def parse_cora_account(text):
    dre = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+Saldo do dia")
    tre = re.compile(r"^\s{2,}(.*?)\s{2,}.*?([+\-])\s*R\$\s*([\d.,]+)\s*$")
    rows = []
    cur = None
    for ln in text.splitlines():
        dm = dre.match(ln)
        if dm:
            cur = datetime.strptime(dm.group(1), "%d/%m/%Y").date()
            continue
        tm = tre.match(ln)
        if tm and cur:
            desc, sign, val = tm.group(1).strip(), tm.group(2), brl(tm.group(3))
            if sign == "+":
                rows.append(_tx(cur, "PJ", "Cora (Youup)", desc, val or 0, 0, "Receita",
                                categorizar(desc, "Receita"), "Cora (Youup)"))
            else:
                cat = ("Pagamento fatura cartão Cora (PJ, sem detalhamento)"
                       if "fatura" in norm(desc) else categorizar(desc))
                rows.append(_tx(cur, "PJ", "Cora (Youup)", desc, 0, val or 0, "Despesa", cat, "Cora (Youup)"))
    return rows


def parse_pagbank(text):
    pre = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}:\d{2}\s+[0-9A-F\-]{20,}\s+(.*?)\s+"
                     r"(A receber|Dispon[ií]vel)\s+(-?[\d.]+,\d{2})\s*$")
    rows = []
    for ln in text.splitlines():
        m = pre.match(ln)
        if not m:
            continue
        dt = datetime.strptime(m.group(1), "%d/%m/%Y").date()
        desc, conta, val = m.group(2).strip(), m.group(3), brl(m.group(4))
        nd = norm(desc)
        obs = f"PagBank (Youup) | {conta}"
        if conta.startswith("Dispon"):
            rows.append(_tx(dt, "PJ", "PagBank (Youup)", desc, val if val > 0 else 0,
                            abs(val) if val < 0 else 0, "Liquidação/Interno (adquirente)",
                            "Liquidação/transferência interna", obs))
        elif "venda pela moderninha" in nd:
            rows.append(_tx(dt, "PJ", "PagBank (Youup)", desc, val or 0, 0, "Receita",
                            "Receita - Vendas (maquininha)", obs))
        elif "pagamento de pix do pagbank" in nd:
            rows.append(_tx(dt, "PJ", "PagBank (Youup)", desc, val or 0, 0, "Receita",
                            "Receita - Pix/transferência", obs))
        elif "taxa" in nd:
            rows.append(_tx(dt, "PJ", "PagBank (Youup)", desc, 0, abs(val) if val else 0, "Despesa",
                            "Adquirência (taxas maquininha)", obs))
        elif "pagamento liberado" in nd:
            rows.append(_tx(dt, "PJ", "PagBank (Youup)", desc, val if val > 0 else 0,
                            abs(val) if val < 0 else 0, "Liquidação/Interno (adquirente)",
                            "Liquidação/transferência interna", obs))
        else:
            if val and val < 0:
                rows.append(_tx(dt, "PJ", "PagBank (Youup)", desc, 0, abs(val), "Despesa", categorizar(desc), obs))
            else:
                rows.append(_tx(dt, "PJ", "PagBank (Youup)", desc, val or 0, 0, "Receita",
                                categorizar(desc, "Receita"), obs))
    return rows


def _fatura_mes(text):
    m = re.search(r"fatura de (janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)", text, re.I)
    if m:
        return MESES.get(norm(m.group(1)))
    m = re.search(r"VENCIMENTO\s+\d{2}/(\d{2})/", text)
    if m:
        return int(m.group(1))
    return None


def parse_caixa_card(text_raw, fmes):
    cx_line = re.compile(r"^(\d{2})/(\d{2})\s+(.+?)\s+([\d.]+,\d{2})\s*([DC])\s*$")
    cx_anu = re.compile(r"^(ANUIDADE.+?)\s+([\d.]+,\d{2})\s*([DC])\s*$", re.I)
    rows = []
    obs_tag = f"Cartão Caixa 1016 | fatura {fmes:02d}"
    for ln in text_raw.splitlines():
        s = ln.strip()
        am = cx_anu.match(s)
        if am:
            try:
                dt = date(ANO_PADRAO, fmes, 1)
            except ValueError:
                dt = None
            rows.append(_tx(dt, "PF", "Cartão Caixa (1016)", am.group(1).strip(), 0, brl(am.group(2)),
                            "Despesa", "Tarifas e juros bancários", obs_tag))
            continue
        m = cx_line.match(s)
        if not m:
            continue
        dd, mm, desc, val, dc = m.groups()
        desc = re.sub(r"\s{2,}", " ", desc).strip()
        nd = norm(desc)
        if nd.startswith("total"):
            continue
        v = brl(val)
        try:
            dt = date(ANO_PADRAO, int(mm), int(dd))
        except ValueError:
            dt = None
        if "total da fatura anterior" in nd:
            rows.append(_tx(dt, "PF", "Cartão Caixa (1016)", desc, v, 0,
                            "Saldo transportado (fatura anterior)", "Saldo transportado (memo)", obs_tag))
        elif "obrigado pelo pagamento" in nd or (dc == "C" and "pagamento" in nd):
            rows.append(_tx(dt, "PF", "Cartão Caixa (1016)", desc, v, 0,
                            "Pagamento de fatura de cartão", "Pagamento de fatura de cartão", obs_tag))
        elif dc == "C":
            rows.append(_tx(dt, "PF", "Cartão Caixa (1016)", desc, v, 0, "Estorno/Devolução",
                            "Estorno/Devolução", obs_tag))
        else:
            cat = categorizar(desc)
            if "youup" in nd:
                cat = "Transferência PF↔PJ (Youup)"
            elif any(k in nd for k in ["anuidade", "iof", "juros", "multa", "mora"]):
                cat = "Tarifas e juros bancários"
            rows.append(_tx(dt, "PF", "Cartão Caixa (1016)", desc, 0, v, "Despesa", cat, obs_tag))
    return rows


def parse_mp_card(text_raw, fmes):
    mp_row = re.compile(r"^(\d{2})/(\d{2})\s+(.+?)\s+(?:Parcela\s+\d+\s+de\s+\d+\s+)?R\$\s*([\d.]+,\d{2})\s*$")
    rows = []
    section = None
    for ln in text_raw.splitlines():
        s = ln.strip()
        nl = norm(s)
        if "movimentacoes na fatura" in nl:
            section = "mov"; continue
        if "cartao visa" in nl and "1347" in nl:
            section = "visa"; continue
        if nl.startswith("total") or nl.startswith("detalhes de consumo") or nl.startswith("data "):
            continue
        m = mp_row.match(s)
        if not m or section is None:
            continue
        dd, mm, desc, val = m.groups()
        desc = re.sub(r"\s{2,}", " ", desc).strip()
        nd = norm(desc)
        v = brl(val)
        try:
            dt = date(ANO_PADRAO, int(mm), int(dd))
        except ValueError:
            dt = None
        obs = f"Cartão MP 1347 | fatura {fmes:02d}"
        p = re.search(r"Parcela\s+\d+\s+de\s+\d+", ln)
        if p:
            obs += " | " + p.group(0)
        if section == "mov":
            if "pagamento da fatura" in nd:
                rows.append(_tx(dt, "PF", "Cartão Mercado Pago (1347)", desc, v, 0,
                                "Pagamento de fatura de cartão", "Pagamento de fatura de cartão", obs))
            elif "credito" in nd:
                rows.append(_tx(dt, "PF", "Cartão Mercado Pago (1347)", desc, v, 0, "Estorno/Devolução",
                                "Estorno/Devolução", obs))
            elif any(k in nd for k in ["juros", "iof", "multa", "mora", "encargo"]):
                rows.append(_tx(dt, "PF", "Cartão Mercado Pago (1347)", desc, 0, v, "Despesa",
                                "Tarifas e juros bancários", obs))
            else:
                rows.append(_tx(dt, "PF", "Cartão Mercado Pago (1347)", desc, 0, v, "Despesa",
                                categorizar(desc), obs))
        else:
            rows.append(_tx(dt, "PF", "Cartão Mercado Pago (1347)", desc, 0, v, "Despesa", categorizar(desc), obs))
    return rows


def _cora_card_cat(desc):
    d = desc.upper()
    if any(k in d for k in ["FACEBK", "FACEBOOK", "GOOGLE ADS", "GREATPAGES", "MLABS"]):
        return "Marketing"
    if "KIWIFY" in d:
        return "Software/Cursos/Comunidades"
    return "Assinaturas/Serviços digitais"


def parse_cora_card(text_raw):
    """Fatura do cartão Cora (PJ): usa a seção 'Lançamentos DD/MM a DD/MM'."""
    row = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d.]+,\d{2})\s*$")
    fm = re.search(r"fatura de (\w+)", text_raw, re.I)
    fmes = MESES.get(norm(fm.group(1))) if fm else None
    tag = f"Cartão Cora | fatura {fmes:02d}" if fmes else "Cartão Cora"
    rows = []
    inseç = False
    for ln in text_raw.splitlines():
        s = ln.strip()
        if s.startswith("Lançamentos") and " a " in s:
            inseç = True; continue
        if not inseç:
            continue
        if s.startswith(("Cora Sociedade", "CNPJ", "Limite", "Data ")):
            continue
        m = row.match(s)
        if m:
            dt = datetime.strptime(m.group(1), "%d/%m/%Y").date()
            desc = m.group(2).strip()
            rows.append(_tx(dt, "PJ", "Cartão Cora (Youup)", desc, 0, brl(m.group(3)),
                            "Despesa", _cora_card_cat(desc), tag))
    return rows

# ───────────────────────── importadores universais ─────────────────────────
def _ofx_org(text):
    for tag in ("ORG", "BANKID", "ACCTID"):
        m = re.search(rf"<{tag}>\s*([^<\r\n]+)", text, re.I)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def parse_ofx(text, escopo="PF", fonte=None):
    """Lê um arquivo OFX (extrato ou fatura) em lançamentos normalizados.

    OFX é o formato padrão exportado pelos bancos no Internet Banking — 1 arquivo
    do período inteiro, estruturado. escopo/fonte são definidos por quem importa
    (a conta escolhida); por padrão PF, e o usuário reclassifica se preciso.
    """
    if not fonte:
        org = _ofx_org(text)
        fonte = f"Conta {org}" if org else "Conta (OFX)"
    rows = []
    for blk in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.S | re.I):
        def g(tag):
            m = re.search(rf"<{tag}>\s*([^<\r\n]+)", blk, re.I)
            return m.group(1).strip() if m else ""
        raw = g("DTPOSTED")[:8]
        try:
            dt = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        except (ValueError, IndexError):
            dt = None
        try:
            val = float(g("TRNAMT").replace(",", "."))
        except ValueError:
            continue
        desc = (g("MEMO") or g("NAME") or g("TRNTYPE")).strip()
        nd = norm(desc)
        if "fatura" in nd and ("cartao" in nd or "pagamento" in nd):
            rows.append(_tx(dt, escopo, fonte, desc, abs(val) if val < 0 else 0, 0,
                            "Pagamento de fatura de cartão", "Pagamento de fatura de cartão", "OFX"))
        elif is_own(desc) and ("pix" in nd or "transf" in nd):
            rows.append(_tx(dt, escopo, fonte, desc, val if val > 0 else 0,
                            abs(val) if val < 0 else 0, "Transferência entre contas próprias",
                            "Transferência entre contas próprias", "OFX"))
        elif val < 0:
            rows.append(_tx(dt, escopo, fonte, desc, 0, abs(val), "Despesa", categorizar(desc), "OFX"))
        else:
            rows.append(_tx(dt, escopo, fonte, desc, val, 0, "Receita", categorizar(desc, "Receita"), "OFX"))
    return rows


def parse_excel_modelo(path, escopo="PF", fonte="Importação Excel"):
    """Lê a planilha-modelo (colunas Data, Descrição, Valor). Plano B universal."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    hdr = c_data = c_desc = c_val = None
    for r in range(1, min(ws.max_row or 1, 10) + 1):
        cols = {}
        for c in range(1, (ws.max_column or 1) + 1):
            v = ws.cell(r, c).value
            if v is not None:
                cols[norm(v)] = c
        if {"data", "descricao", "valor"} <= set(cols):
            hdr, c_data, c_desc, c_val = r, cols["data"], cols["descricao"], cols["valor"]
            break
    if hdr is None:
        return []
    rows = []
    for r in range(hdr + 1, (ws.max_row or hdr) + 1):
        dv, desc, vv = ws.cell(r, c_data).value, ws.cell(r, c_desc).value, ws.cell(r, c_val).value
        if dv is None or vv is None:
            continue
        if isinstance(dv, datetime):
            dt = dv.date()
        elif isinstance(dv, date):
            dt = dv
        else:
            dt = None
            for f in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
                try:
                    dt = datetime.strptime(str(dv).strip()[:10], f).date(); break
                except ValueError:
                    pass
        val = vv if isinstance(vv, (int, float)) else brl(vv)
        if val is None:
            continue
        desc = str(desc or "").strip()
        if val < 0:
            rows.append(_tx(dt, escopo, fonte, desc, 0, abs(val), "Despesa", categorizar(desc), "Excel"))
        else:
            rows.append(_tx(dt, escopo, fonte, desc, val, 0, "Receita", categorizar(desc, "Receita"), "Excel"))
    return rows


def modelo_excel_bytes():
    """Gera a planilha-modelo (Data/Descrição/Valor) para download."""
    import io
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lançamentos"
    ws.append(["Data", "Descrição", "Valor"])
    ws.append(["15/01/2026", "Exemplo: mercado", -134.60])
    ws.append(["20/01/2026", "Exemplo: recebimento PIX", 1500.00])
    for col, w in (("A", 14), ("B", 40), ("C", 14)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ───────────────────────── reconciliação entre fontes ─────────────────────────
def reconcile(tx):
    """Reclassifica pagamentos de fatura entre fontes p/ evitar dupla contagem."""
    fontes = {t["fonte"] for t in tx}
    tem_cora_card = "Cartão Cora (Youup)" in fontes
    mp_fatura_val = set()  # totais das faturas MP (para casar pagamentos no extrato)
    # (os totais são captados no process(); aqui só usamos o set passado via atributo)
    for t in tx:
        nd = norm(t["descricao"])
        # pagamentos "Cartões Caixa" nos extratos -> memo
        if t["fonte"] in ("Itaú conta corrente", "BTG conta corrente") and t["tipo"] == "Despesa" \
                and ("cartoes caixa" in nd or "cartao caixa" in nd):
            t["tipo"] = t["categoria"] = "Pagamento de fatura de cartão"
            t["obs"] = (t["obs"] + " | reclass. cartão Caixa").strip(" |")
        # pagamentos da fatura Cora no extrato Cora -> memo (quando há o cartão itemizado)
        if tem_cora_card and t["fonte"] == "Cora (Youup)" and "pagamento da fatura" in nd:
            t["tipo"] = t["categoria"] = "Pagamento de fatura de cartão"
            t["obs"] = (t["obs"] + " | reclass. cartão Cora").strip(" |")
    return tx


# ───────────────────────── orquestração ─────────────────────────
def _hash(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def process(paths):
    """Recebe uma lista de caminhos de arquivos; devolve (tx, report)."""
    # 1) deduplicar por conteúdo
    seen, unique = set(), []
    for p in paths:
        h = _hash(p)
        if h in seen:
            continue
        seen.add(h)
        unique.append(p)

    tx = []
    report = {"arquivos": [], "ignorados": [], "checagens": []}
    mp_fatura_val = set()

    for p in unique:
        src = detect_source(p)
        nome = os.path.basename(p)
        try:
            if src in ("itau_card_6434", "itau_card_4482"):
                numero = "6434" if src.endswith("6434") else "4482"
                new = parse_itau_card(p, numero)
            elif src == "btg_card":
                new = parse_btg_card(p)
            elif src == "btg_account":
                new = parse_btg_account(pdf_text(p, layout=True))
            elif src == "itau_account":
                new = parse_itau_account(pdf_text(p, layout=True))
            elif src == "cora_account":
                new = parse_cora_account(pdf_text(p, layout=True))
            elif src == "pagbank":
                new = parse_pagbank(pdf_text(p, layout=True))
            elif src == "caixa_card":
                raw = pdf_text(p, layout=False)
                new = parse_caixa_card(raw, _fatura_mes(raw) or 1)
            elif src == "mp_card":
                raw = pdf_text(p, layout=False)
                fm = _fatura_mes(raw) or 1
                mm = re.search(r"Total a pagar\s*[-\s]*R\$\s*([\d.]+,\d{2})", raw)
                if mm:
                    mp_fatura_val.add(round(brl(mm.group(1)), 2))
                new = parse_mp_card(raw, fm)
            elif src == "cora_card":
                new = parse_cora_card(pdf_text(p, layout=False))
            elif src == "ofx":
                with open(p, "r", encoding="latin-1", errors="ignore") as fh:
                    new = parse_ofx(fh.read())
            elif src == "excel_modelo":
                new = parse_excel_modelo(p)
            else:
                report["ignorados"].append(nome)
                continue
        except Exception as e:  # noqa
            report["ignorados"].append(f"{nome} (erro: {e})")
            continue
        tx.extend(new)
        report["arquivos"].append({"arquivo": nome, "origem": src, "lancamentos": len(new)})

    # reclassificação de pagamentos MP no extrato (casando por valor)
    for t in tx:
        if t["fonte"] in ("Itaú conta corrente", "BTG conta corrente") and t["tipo"] == "Despesa" \
                and "mercado pago instituicao" in norm(t["descricao"]) and round(t["saida"], 2) in mp_fatura_val:
            t["tipo"] = t["categoria"] = "Pagamento de fatura de cartão"
            t["obs"] = (t["obs"] + " | reclass. cartão Mercado Pago").strip(" |")

    reconcile(tx)

    # ordenar
    tx.sort(key=lambda t: (t["escopo"], t["fonte"], t["data"] or date(ANO_PADRAO, 1, 1)))

    # reconciliação por fonte
    by = defaultdict(lambda: [0, 0.0, 0.0])
    for t in tx:
        by[t["fonte"]][0] += 1
        by[t["fonte"]][1] += t["entrada"]
        by[t["fonte"]][2] += t["saida"]
    report["por_fonte"] = [{"fonte": k, "n": v[0], "entradas": round(v[1], 2), "saidas": round(v[2], 2)}
                           for k, v in sorted(by.items())]
    report["total"] = len(tx)
    return tx, report
