# -*- coding: utf-8 -*-
"""
Assistente de linguagem natural — o núcleo da entrada por WhatsApp (Fase 2).

Transforma uma frase solta em um lançamento estruturado, sem depender de nuvem
externa (é determinístico, então é testável e não vaza dado). Quando o WhatsApp
estiver ligado (n8n → Evolution → este parser), cada mensagem do Iuri vira um
rascunho de lançamento; voz vira texto antes (transcrição) e cai aqui igual.

Exemplos que entende:
    "gastei 50 no ifood"                    → Despesa R$50, Alimentação, PF
    "paguei 89,90 de energia"               → Despesa R$89,90, Energia elétrica, PF
    "recebi 1200 na maquininha"             → Receita R$1200, Vendas, PJ
    "recebi 3000 pix da youup"              → Receita PJ (e marca como possível transferência)
    "transferi 2000 da youup pra minha conta" → sinaliza transferência interna
    "1500 aluguel ontem"                    → Despesa R$1500, Moradia, PF, data de ontem

Não grava nada — devolve um dict para o app confirmar/salvar. A regra de ouro do
projeto continua: nada entra sem o Iuri ver (ou sem regra explícita dele).
"""
import re
from datetime import date, timedelta

from .pipeline import categorizar, norm

_RECEITA = ["recebi", "recebimento", "recebido", "entrou", "ganhei", "vendi",
            "venda", "caiu", "recebendo", "salario", "salário", "pró-labore",
            "pro labore", "prolabore", "faturei", "faturamento", "honorario"]
_DESPESA = ["gastei", "paguei", "pagamento", "comprei", "compra", "saiu",
            "despesa", "gasto", "conta de", "boleto", "fatura", "parcela",
            "assinatura", "mensalidade"]
_TRANSF = ["transferi", "transferencia", "transferência", "mandei", "passei",
            "enviei pra", "mandar pra", "tirei da", "saquei", "pix pra mim",
            "pra minha conta", "entre contas", "da youup pra", "da clinica pra"]
_PJ = ["youup", "clinica", "clínica", "pj", "maquininha", "moderninha",
       "pagbank", "cnpj", "empresa", "consultorio", "consultório", "paciente"]

_MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
          "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}

# palavras do dia a dia → categoria (a fala é diferente do extrato do banco)
_NL_CAT = [
    ("Receita - Vendas (maquininha)", ["maquininha", "maquineta", "moderninha", "cartao paciente"]),
    ("Energia elétrica", ["energia", "luz", "conta de luz"]),
    ("Água/Saneamento", ["agua", "água", "saneamento"]),
    ("Telefonia/Internet", ["internet", "celular", "telefone", "wifi", "wi-fi"]),
    ("Moradia/Condomínio", ["aluguel", "condominio", "condomínio", "iptu"]),
    ("Alimentação/Restaurante", ["ifood", "almoco", "almoço", "janta", "lanche",
                                 "restaurante", "pizza", "hamburguer", "acai", "açaí", "cafe"]),
    ("Supermercado", ["mercado", "supermercado", "feira", "compras do mes"]),
    ("Combustível", ["gasolina", "combustivel", "combustível", "posto", "etanol", "diesel"]),
    ("Saúde/Farmácia", ["farmacia", "farmácia", "remedio", "remédio", "medico", "médico", "exame", "dentista"]),
    ("Transporte/Viagens", ["uber", "99", "taxi", "táxi", "passagem", "viagem"]),
    ("Assinaturas/Serviços digitais", ["netflix", "spotify", "assinatura", "apple", "google", "chatgpt"]),
    ("Educação/Cursos", ["curso", "mentoria", "faculdade", "escola", "aula"]),
    ("Salário/Pró-labore", ["salario", "salário", "pro labore", "pró-labore", "prolabore"]),
]


def _nl_categoria(texto, fallback):
    from .pipeline import norm as _n
    d = _n(texto)
    for cat, keys in _NL_CAT:
        if any(k in d for k in keys):
            return cat
    return fallback


def _valor(texto):
    """Extrai o primeiro valor monetário. Aceita 1.200,50 / 89,90 / 50 / R$ 50."""
    t = texto.replace("R$", " ").replace("r$", " ")
    # 1.234,56  ou  1234,56
    m = re.search(r"\b(\d{1,3}(?:\.\d{3})+,\d{2})\b", t)
    if m:
        return float(m.group(1).replace(".", "").replace(",", "."))
    m = re.search(r"\b(\d+,\d{2})\b", t)
    if m:
        return float(m.group(1).replace(",", "."))
    # 1.200 (milhar sem centavos) — só se tiver o ponto de milhar
    m = re.search(r"\b(\d{1,3}(?:\.\d{3})+)\b", t)
    if m:
        return float(m.group(1).replace(".", ""))
    m = re.search(r"\b(\d+(?:\.\d{1,2})?)\b", t)  # 50 ou 50.5
    if m:
        return float(m.group(1))
    return None


def _data(texto, hoje=None):
    hoje = hoje or date.today()
    d = norm(texto)
    if "anteontem" in d:
        return hoje - timedelta(days=2)
    if "ontem" in d:
        return hoje - timedelta(days=1)
    # dd/mm  ou  dd/mm/aaaa
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", texto)
    if m:
        dia, mes = int(m.group(1)), int(m.group(2))
        ano = int(m.group(3)) if m.group(3) else hoje.year
        if ano < 100:
            ano += 2000
        try:
            return date(ano, mes, dia)
        except ValueError:
            pass
    # "dia 5", "5 de março"
    m = re.search(r"\b(\d{1,2})\s+de\s+([a-zç]{3,})", d)
    if m and m.group(2)[:3] in _MESES:
        try:
            return date(hoje.year, _MESES[m.group(2)[:3]], int(m.group(1)))
        except ValueError:
            pass
    return hoje


def interpretar(texto, hoje=None):
    """Frase → rascunho de lançamento. Nunca grava; devolve dict com `ok`.

    Retorno:
      {ok, tipo, valor, escopo, categoria, descricao, data,
       transferencia (bool), confianca, aviso}
    """
    hoje = hoje or date.today()
    original = (texto or "").strip()
    d = norm(original)
    if not d:
        return {"ok": False, "aviso": "Mensagem vazia."}

    valor = _valor(original)
    if not valor or valor <= 0:
        return {"ok": False, "aviso": "Não achei um valor em reais na mensagem. "
                "Ex.: \"gastei 50 no ifood\"."}

    is_transf = any(p in d for p in _TRANSF)
    is_receita = any(p in d for p in _RECEITA)
    is_despesa = any(p in d for p in _DESPESA)
    # desempate: sem pista clara, valor "recebido/entrou" → receita, senão despesa
    if is_receita and not is_despesa:
        tipo = "Receita"
    elif is_despesa and not is_receita:
        tipo = "Despesa"
    else:
        tipo = "Receita" if is_receita else "Despesa"

    escopo = "PJ" if any(p in d for p in _PJ) else "PF"

    # descrição = frase sem os verbos/preposições comuns e sem o número
    desc = re.sub(r"\bR\$\s*[\d.,]+\b", "", original, flags=re.I)
    desc = re.sub(r"\b[\d.,]+\b", "", desc)
    for w in ("gastei", "paguei", "recebi", "comprei", "de ", "no ", "na ",
              "em ", "com ", "do ", "da ", "pra ", "para ", "reais", "r$"):
        desc = re.sub(rf"\b{re.escape(w)}", "", desc, flags=re.I)
    desc = re.sub(r"\s+", " ", desc).strip(" .,-") or ("Recebimento" if tipo == "Receita" else "Despesa")

    categoria = _nl_categoria(original, categorizar(desc if desc else original, tipo))
    aviso = None
    if is_transf:
        aviso = ("Isso parece uma transferência entre suas contas — o motor "
                 "anti-duplicação vai sugerir neutralizar para não contar 2x.")

    return {
        "ok": True,
        "tipo": tipo,
        "valor": round(valor, 2),
        "escopo": escopo,
        "categoria": categoria,
        "descricao": desc[:80].capitalize(),
        "data": _data(original, hoje).isoformat(),
        "transferencia": is_transf,
        "confianca": "alta" if (is_receita or is_despesa or is_transf) else "média",
        "aviso": aviso,
    }


def para_lancamento(interp):
    """Converte a interpretação em um dict pronto para store.save_transactions."""
    if not interp.get("ok"):
        return None
    v = float(interp["valor"])
    return {
        "data": interp["data"], "escopo": interp["escopo"],
        "fonte": "WhatsApp", "descricao": interp["descricao"],
        "entrada": v if interp["tipo"] == "Receita" else 0.0,
        "saida": v if interp["tipo"] == "Despesa" else 0.0,
        "tipo": interp["tipo"], "categoria": interp["categoria"], "obs": "whatsapp",
    }
