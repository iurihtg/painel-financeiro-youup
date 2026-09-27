# -*- coding: utf-8 -*-
"""
Backend Supabase (Postgres na nuvem) — mesma API do store.py (SQLite local).

Ativa quando as variáveis de ambiente SUPABASE_URL e SUPABASE_KEY existem
(veja contabil/db.py). Assim o mesmo app funciona local (SQLite) ou na nuvem
(Supabase) sem mudar o resto do código.

Fala com o Supabase pela API REST (PostgREST). O schema das tabelas está em
`supabase_schema.sql` — rode-o uma vez no editor SQL do Supabase.
"""
import os
import requests
from datetime import datetime

from .store import assign_ids, _iso  # reaproveita id determinístico e ISO

CAMPOS = ["data", "escopo", "fonte", "descricao", "entrada", "saida", "tipo", "categoria", "obs"]


def _cfg():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL/SUPABASE_KEY não configurados.")
    return url, key


def _headers(extra=None):
    _, key = _cfg()
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _rest(path):
    url, _ = _cfg()
    return f"{url}/rest/v1/{path}"


# ───────────────────────── transações ─────────────────────────
def save_transactions(tx, db_path=None):
    """Insere lançamentos novos (dedup por id na PK). Retorna (inseridos, ignorados)."""
    if not tx:
        return 0, 0
    ts = datetime.now().isoformat(timespec="seconds")
    rows = []
    for tid, t in assign_ids(tx):
        rows.append({
            "id": tid, "data": _iso(t.get("data")), "escopo": t.get("escopo"),
            "fonte": t.get("fonte"), "descricao": t.get("descricao"),
            "entrada": float(t.get("entrada") or 0), "saida": float(t.get("saida") or 0),
            "tipo": t.get("tipo"), "categoria": t.get("categoria"),
            "categoria_manual": None, "obs": t.get("obs"), "import_ts": ts,
        })
    inseridos = 0
    # lotes de 500 para não estourar payload
    for i in range(0, len(rows), 500):
        lote = rows[i:i + 500]
        r = requests.post(
            _rest("transactions"),
            headers=_headers({"Prefer": "resolution=ignore-duplicates,return=representation"}),
            json=lote, timeout=60,
        )
        r.raise_for_status()
        inseridos += len(r.json() or [])
    return inseridos, len(rows) - inseridos


def load_transactions(db_path=None, escopo=None, inicio=None, fim=None):
    params = ["select=*", "order=data.asc,escopo.asc,fonte.asc"]
    if escopo in ("PF", "PJ"):
        params.append(f"escopo=eq.{escopo}")
    if inicio:
        params.append(f"data=gte.{_iso(inicio)}")
    if fim:
        params.append(f"data=lte.{_iso(fim)}")
    r = requests.get(_rest("transactions?" + "&".join(params)), headers=_headers(), timeout=60)
    r.raise_for_status()
    out = []
    for d in r.json():
        d["categoria_auto"] = d.get("categoria")
        if d.get("categoria_manual"):
            d["categoria"] = d["categoria_manual"]
        out.append(d)
    return out


def set_categoria_manual(tx_id, categoria, db_path=None):
    r = requests.patch(
        _rest(f"transactions?id=eq.{tx_id}"),
        headers=_headers({"Prefer": "return=minimal"}),
        json={"categoria_manual": categoria or None}, timeout=30,
    )
    r.raise_for_status()


def delete_transaction(tx_id, db_path=None):
    r = requests.delete(_rest(f"transactions?id=eq.{tx_id}"),
                        headers=_headers({"Prefer": "return=minimal"}), timeout=30)
    r.raise_for_status()


def set_tipo(tx_id, tipo, db_path=None):
    """Muda o `tipo` de um lançamento (neutraliza transferências internas)."""
    r = requests.patch(
        _rest(f"transactions?id=eq.{tx_id}"),
        headers=_headers({"Prefer": "return=minimal"}),
        json={"tipo": tipo}, timeout=30,
    )
    r.raise_for_status()


def count_transactions(db_path=None):
    r = requests.get(
        _rest("transactions?select=id"),
        headers=_headers({"Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"}),
        timeout=30,
    )
    cr = r.headers.get("Content-Range", "")
    if "/" in cr:
        try:
            return int(cr.split("/")[-1])
        except ValueError:
            pass
    return len(r.json() or [])


def clear_transactions(db_path=None):
    r = requests.delete(_rest("transactions?id=neq.__none__"),
                        headers=_headers({"Prefer": "return=minimal"}), timeout=60)
    r.raise_for_status()


# ───────────────────────── overrides de recorrentes ─────────────────────────
def load_overrides(db_path=None):
    r = requests.get(_rest("recurring_overrides?select=*"), headers=_headers(), timeout=30)
    r.raise_for_status()
    return {row["chave"]: row for row in r.json()}


def save_override(chave, label, categoria, escopo, valor, dia=None, ativo=True, origem="manual",
                  db_path=None):
    row = {"chave": chave, "label": label, "categoria": categoria, "escopo": escopo,
           "valor": float(valor or 0), "dia": int(dia) if dia else None,
           "ativo": bool(ativo), "origem": origem}
    r = requests.post(
        _rest("recurring_overrides"),
        headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
        json=row, timeout=30,
    )
    r.raise_for_status()


def delete_override(chave, db_path=None):
    r = requests.delete(_rest(f"recurring_overrides?chave=eq.{chave}"),
                        headers=_headers({"Prefer": "return=minimal"}), timeout=30)
    r.raise_for_status()


# ───────────────────────── settings ─────────────────────────
def get_setting(chave, default=None, db_path=None):
    import json
    r = requests.get(_rest(f"settings?chave=eq.{chave}&select=valor"), headers=_headers(), timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data:
        return default
    try:
        return json.loads(data[0]["valor"])
    except (ValueError, TypeError, KeyError):
        return default


def set_setting(chave, valor, db_path=None):
    import json
    row = {"chave": chave, "valor": json.dumps(valor, ensure_ascii=False)}
    r = requests.post(
        _rest("settings"),
        headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
        json=row, timeout=30,
    )
    r.raise_for_status()
