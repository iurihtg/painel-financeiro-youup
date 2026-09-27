# -*- coding: utf-8 -*-
"""
Seletor de backend de persistência.

- Se SUPABASE_URL e SUPABASE_KEY estão no ambiente  -> Supabase (nuvem).
- Senão                                             -> SQLite local (data/historico.db).

O resto do app usa sempre `from contabil import db` e `st = db.active()`,
sem se preocupar com qual backend está ativo (a API é idêntica).
"""
import os

from . import store as _sqlite


def active():
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        from . import store_supabase as _sb
        return _sb
    return _sqlite


def backend_nome():
    return "Supabase (nuvem)" if (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")) \
        else "SQLite (local)"
