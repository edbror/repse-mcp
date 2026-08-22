"""Tests del gate freemium (quota.py) con un Turso falso en memoria (sqlite3)."""
from __future__ import annotations

import dataclasses
import sqlite3

import pytest

from repse import quota
from repse.config import settings


class _Res:
    def __init__(self, rows):
        self.rows = rows


class _FakeClient:
    """Imita el client de libsql: .execute(sql, args) -> .rows, y .close()."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(self, sql, args=None):
        return _Res(self._conn.execute(sql, args or []).fetchall())

    def close(self):  # no cerramos la conexión compartida del test
        pass


class _Tok:
    def __init__(self, sub=None, client_id=None):
        self.claims = {"sub": sub} if sub else {}
        self.client_id = client_id


def _cfg(**overrides):
    base = dataclasses.replace(settings, turso_url="libsql://fake", free_daily_limit=1)
    return dataclasses.replace(base, **overrides) if overrides else base


@pytest.fixture
def turso_mem(monkeypatch):
    conn = sqlite3.connect(":memory:")
    monkeypatch.setattr(quota.turso, "_client", lambda: _FakeClient(conn))
    monkeypatch.setattr(quota, "settings", _cfg())
    monkeypatch.setattr(quota, "_ensured", False)
    yield conn
    conn.close()


def test_primera_pasa_segunda_se_bloquea(turso_mem):
    tok = _Tok(sub="user-a")
    assert quota.check(tok) is None
    bloqueado = quota.check(tok)
    assert bloqueado is not None
    assert bloqueado["error"] == "limite_gratis_alcanzado"
    assert bloqueado["consultas_hoy"] == 2
    assert bloqueado["limite_gratis"] == 1


def test_usuarios_distintos_cuentan_por_separado(turso_mem):
    assert quota.check(_Tok(sub="u1")) is None
    assert quota.check(_Tok(sub="u2")) is None


def test_key_estatica_de_watr_es_ilimitada(turso_mem):
    tok = _Tok(client_id="watr-static-key")
    for _ in range(5):
        assert quota.check(tok) is None


def test_usuario_pagado_es_ilimitado(monkeypatch):
    conn = sqlite3.connect(":memory:")
    monkeypatch.setattr(quota.turso, "_client", lambda: _FakeClient(conn))
    monkeypatch.setattr(quota, "settings", _cfg(paid_user_ids=frozenset({"vip"})))
    monkeypatch.setattr(quota, "_ensured", False)
    tok = _Tok(sub="vip")
    for _ in range(5):
        assert quota.check(tok) is None
    conn.close()


def test_falla_abierto_sin_identidad(turso_mem):
    assert quota.check(None) is None
    assert quota.check(_Tok()) is None


def test_falla_abierto_si_turso_apagado(monkeypatch):
    monkeypatch.setattr(quota, "settings", dataclasses.replace(settings, turso_url=""))
    assert quota.check(_Tok(sub="x")) is None
