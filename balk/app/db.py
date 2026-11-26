"""SQLite: produtores, análises, log de alertas, cache e escalonamentos."""
import json
import sqlite3
from datetime import datetime
from typing import Optional

from app import config
from app.models import Producer

SCHEMA = """
CREATE TABLE IF NOT EXISTS producers (
  id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT UNIQUE NOT NULL, channel TEXT,
  lat REAL, lon REAL, crop TEXT, planting_date TEXT, consent INTEGER DEFAULT 0,
  lang TEXT DEFAULT 'pt', source TEXT DEFAULT 'direto', location_precision TEXT DEFAULT 'ponto',
  state TEXT DEFAULT 'INICIO', active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT, producer_id INTEGER, created_at TEXT, result_json TEXT);
CREATE TABLE IF NOT EXISTS alert_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, producer_id INTEGER, type TEXT, sent_at TEXT);
CREATE TABLE IF NOT EXISTS cache (
  key TEXT PRIMARY KEY, value TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS escalations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, producer_id INTEGER, phone TEXT, created_at TEXT, note TEXT);
"""

_FIELDS = ["phone", "channel", "lat", "lon", "crop", "planting_date", "consent", "lang",
           "source", "location_precision", "state", "active"]


def connect() -> sqlite3.Connection:
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _to_producer(row: sqlite3.Row) -> Producer:
    d = dict(row)
    d["consent"] = bool(d["consent"])
    d["active"] = bool(d["active"])
    d.pop("created_at", None)
    return Producer(**d)


def create_producer(p: Producer) -> Producer:
    vals = [int(getattr(p, f)) if isinstance(getattr(p, f), bool) else getattr(p, f) for f in _FIELDS]
    with connect() as con:
        cur = con.execute(
            f"INSERT INTO producers ({','.join(_FIELDS)}, created_at) VALUES ({','.join('?' * len(_FIELDS))}, ?)",
            vals + [_now()])
        pid = cur.lastrowid
    return get_producer(pid)


def get_producer(pid: int) -> Optional[Producer]:
    with connect() as con:
        row = con.execute("SELECT * FROM producers WHERE id=?", (pid,)).fetchone()
    return _to_producer(row) if row else None


def get_producer_by_phone(phone: str) -> Optional[Producer]:
    with connect() as con:
        row = con.execute("SELECT * FROM producers WHERE phone=?", (phone,)).fetchone()
    return _to_producer(row) if row else None


def update_producer(pid: int, **fields) -> Producer:
    fields = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items() if k in _FIELDS}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        with connect() as con:
            con.execute(f"UPDATE producers SET {sets} WHERE id=?", [*fields.values(), pid])
    return get_producer(pid)


def list_active() -> list[Producer]:
    """Ativos, com consentimento e cadastro completo."""
    with connect() as con:
        rows = con.execute(
            "SELECT * FROM producers WHERE active=1 AND consent=1 AND state='ATIVO' ORDER BY id").fetchall()
    return [_to_producer(r) for r in rows]


def list_by_source(source: str) -> list[Producer]:
    return [p for p in list_active() if p.source == source]


def log_alert(producer_id: int, type_: str, sent_at: Optional[str] = None) -> None:
    with connect() as con:
        con.execute("INSERT INTO alert_log (producer_id, type, sent_at) VALUES (?,?,?)",
                    (producer_id, type_, sent_at or _now()))


def get_alert_log(producer_id: int) -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT type, sent_at FROM alert_log WHERE producer_id=?", (producer_id,)).fetchall()
    return [dict(r) for r in rows]


def save_analysis(producer_id: int, result: dict) -> None:
    with connect() as con:
        con.execute("INSERT INTO analyses (producer_id, created_at, result_json) VALUES (?,?,?)",
                    (producer_id, _now(), json.dumps(result, ensure_ascii=False, default=str)))


def last_analysis(producer_id: int) -> Optional[dict]:
    with connect() as con:
        row = con.execute("SELECT result_json FROM analyses WHERE producer_id=? ORDER BY id DESC LIMIT 1",
                          (producer_id,)).fetchone()
    return json.loads(row["result_json"]) if row else None


def cache_get(key: str, max_age_s: Optional[float] = None) -> Optional[dict]:
    with connect() as con:
        row = con.execute("SELECT value, created_at FROM cache WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    if max_age_s is not None:
        age = (datetime.now() - datetime.fromisoformat(row["created_at"])).total_seconds()
        if age > max_age_s:
            return None
    return json.loads(row["value"])


def cache_set(key: str, value: dict) -> None:
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?,?,?)",
                    (key, json.dumps(value, default=str), _now()))


def reset_all() -> None:
    """Limpa tudo (usado pelo botão 'reiniciar demo' do simulador)."""
    with connect() as con:
        for t in ("producers", "analyses", "alert_log", "cache", "escalations"):
            con.execute(f"DELETE FROM {t}")


def list_all() -> list[Producer]:
    with connect() as con:
        rows = con.execute("SELECT * FROM producers ORDER BY id").fetchall()
    return [_to_producer(r) for r in rows]


def add_escalation(producer_id: Optional[int], phone: str, note: str = "") -> None:
    with connect() as con:
        con.execute("INSERT INTO escalations (producer_id, phone, created_at, note) VALUES (?,?,?,?)",
                    (producer_id, phone, _now(), note))


def list_escalations() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM escalations ORDER BY id").fetchall()]
