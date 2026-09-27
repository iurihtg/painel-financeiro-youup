# -*- coding: utf-8 -*-
"""
Persistência do histórico de lançamentos (SQLite local).

Objetivo: acumular os lançamentos consolidados mês a mês, para que o
dashboard e a previsão enxerguem TODO o histórico — não só o lote atual.

Regras:
  - Deduplicação por conteúdo: reimportar os mesmos arquivos NÃO conta 2x.
    O id de cada lançamento é um hash determinístico dos seus campos +
    um índice de ocorrência dentro do lote (para preservar duplicatas
    legítimas do mesmo dia/valor sem recontar reimportações).
  - Edições de categoria feitas pelo usuário sobrevivem entre rodadas
    (coluna `categoria_manual`); a categoria "efetiva" é a manual, se houver.
  - Overrides de recorrentes e parâmetros de previsão ficam em tabelas
    próprias (`recurring_overrides`, `settings`).

API principal:
  save_transactions(tx, db_path) -> (inseridos, ignorados)
  load_transactions(db_path, ...) -> list[dict]
  set_categoria_manual(id, categoria, db_path)
  load_overrides / save_override / delete_override
  get_setting / set_setting
"""
import os
import json
import sqlite3
import hashlib
from datetime import date, datetime
from collections import Counter

# banco fica em contabil-youup/data/historico.db por padrão
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(os.path.dirname(_PKG_DIR), "data", "historico.db")

CAMPOS = ["data", "escopo", "fonte", "descricao", "entrada", "saida", "tipo", "categoria", "obs"]


# ───────────────────────── conexão / schema ─────────────────────────
def connect(db_path=DEFAULT_DB):
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _init(conn)
    return conn


def _init(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id              TEXT PRIMARY KEY,
            data            TEXT,
            escopo          TEXT,
            fonte           TEXT,
            descricao       TEXT,
            entrada         REAL,
            saida           REAL,
            tipo            TEXT,
            categoria       TEXT,
            categoria_manual TEXT,
            obs             TEXT,
            import_ts       TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_tx_data   ON transactions(data);
        CREATE INDEX IF NOT EXISTS ix_tx_escopo ON transactions(escopo);

        CREATE TABLE IF NOT EXISTS recurring_overrides (
            chave     TEXT PRIMARY KEY,
            label     TEXT,
            categoria TEXT,
            escopo    TEXT,
            valor     REAL,
            dia       INTEGER,
            ativo     INTEGER DEFAULT 1,
            origem    TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            chave TEXT PRIMARY KEY,
            valor TEXT
        );
        """
    )
    conn.commit()


# ───────────────────────── id determinístico ─────────────────────────
def _iso(d):
    if isinstance(d, (date, datetime)):
        return d.isoformat()[:10]
    return "" if d is None else str(d)


def _base_id(t):
    raw = "|".join([
        _iso(t.get("data")),
        str(t.get("escopo") or ""),
        str(t.get("fonte") or ""),
        str(t.get("descricao") or ""),
        f"{float(t.get('entrada') or 0):.2f}",
        f"{float(t.get('saida') or 0):.2f}",
        str(t.get("tipo") or ""),
    ])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def assign_ids(tx):
    """Gera ids determinísticos, com sufixo de ocorrência para duplicatas do lote."""
    counts = Counter()
    out = []
    for t in tx:
        b = _base_id(t)
        counts[b] += 1
        out.append((f"{b}-{counts[b]}", t))
    return out


# ───────────────────────── gravação / leitura ─────────────────────────
def save_transactions(tx, db_path=DEFAULT_DB):
    """Insere lançamentos novos (dedup por id). Retorna (inseridos, ignorados)."""
    conn = connect(db_path)
    ts = datetime.now().isoformat(timespec="seconds")
    inseridos = ignorados = 0
    try:
        for tid, t in assign_ids(tx):
            cur = conn.execute(
                """INSERT OR IGNORE INTO transactions
                   (id, data, escopo, fonte, descricao, entrada, saida, tipo,
                    categoria, categoria_manual, obs, import_ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tid, _iso(t.get("data")), t.get("escopo"), t.get("fonte"),
                 t.get("descricao"), float(t.get("entrada") or 0), float(t.get("saida") or 0),
                 t.get("tipo"), t.get("categoria"), None, t.get("obs"), ts),
            )
            if cur.rowcount:
                inseridos += 1
            else:
                ignorados += 1
        conn.commit()
    finally:
        conn.close()
    return inseridos, ignorados


def load_transactions(db_path=DEFAULT_DB, escopo=None, inicio=None, fim=None):
    """Carrega lançamentos como list[dict]. `categoria` já reflete o override manual.
    `inicio`/`fim` são datas (ou strings ISO) inclusivas."""
    if not os.path.exists(db_path):
        return []
    conn = connect(db_path)
    q = "SELECT * FROM transactions WHERE 1=1"
    args = []
    if escopo in ("PF", "PJ"):
        q += " AND escopo = ?"; args.append(escopo)
    if inicio:
        q += " AND data >= ?"; args.append(_iso(inicio))
    if fim:
        q += " AND data <= ?"; args.append(_iso(fim))
    q += " ORDER BY data, escopo, fonte"
    try:
        rows = conn.execute(q, args).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["categoria_auto"] = d["categoria"]
        if d.get("categoria_manual"):
            d["categoria"] = d["categoria_manual"]
        out.append(d)
    return out


def set_categoria_manual(tx_id, categoria, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute("UPDATE transactions SET categoria_manual=? WHERE id=?",
                     (categoria or None, tx_id))
        conn.commit()
    finally:
        conn.close()


def delete_transaction(tx_id, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
        conn.commit()
    finally:
        conn.close()


def count_transactions(db_path=DEFAULT_DB):
    if not os.path.exists(db_path):
        return 0
    conn = connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    finally:
        conn.close()


def clear_transactions(db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM transactions")
        conn.commit()
    finally:
        conn.close()


# ───────────────────────── overrides de recorrentes ─────────────────────────
def load_overrides(db_path=DEFAULT_DB):
    if not os.path.exists(db_path):
        return {}
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT * FROM recurring_overrides").fetchall()
    finally:
        conn.close()
    return {r["chave"]: dict(r) for r in rows}


def save_override(chave, label, categoria, escopo, valor, dia=None, ativo=True, origem="manual",
                  db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute(
            """INSERT INTO recurring_overrides (chave,label,categoria,escopo,valor,dia,ativo,origem)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(chave) DO UPDATE SET
                 label=excluded.label, categoria=excluded.categoria, escopo=excluded.escopo,
                 valor=excluded.valor, dia=excluded.dia, ativo=excluded.ativo, origem=excluded.origem""",
            (chave, label, categoria, escopo, float(valor or 0),
             int(dia) if dia else None, 1 if ativo else 0, origem),
        )
        conn.commit()
    finally:
        conn.close()


def delete_override(chave, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM recurring_overrides WHERE chave=?", (chave,))
        conn.commit()
    finally:
        conn.close()


# ───────────────────────── settings (chave/valor JSON) ─────────────────────────
def get_setting(chave, default=None, db_path=DEFAULT_DB):
    if not os.path.exists(db_path):
        return default
    conn = connect(db_path)
    try:
        row = conn.execute("SELECT valor FROM settings WHERE chave=?", (chave,)).fetchone()
    finally:
        conn.close()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return row[0]


def set_setting(chave, valor, db_path=DEFAULT_DB):
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO settings (chave,valor) VALUES (?,?) "
            "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
            (chave, json.dumps(valor, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()
