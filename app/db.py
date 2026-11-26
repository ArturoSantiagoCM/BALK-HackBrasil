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
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, producer_id INTEGER, phone TEXT, direction TEXT, channel TEXT, kind TEXT,
  type TEXT, content TEXT, confidence TEXT, evidence_json TEXT, report_token TEXT, provider_id TEXT, state TEXT,
  error TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_messages_producer ON messages (producer_id, kind, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_provider ON messages (provider_id);
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, producer_id INTEGER, phone TEXT UNIQUE NOT NULL, role TEXT DEFAULT 'sucessor',
  state TEXT DEFAULT 'AGUARDA_SIM', created_at TEXT, consent_at TEXT);
CREATE TABLE IF NOT EXISTS consents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, producer_id INTEGER, phone TEXT, purpose TEXT, text_version TEXT,
  granted_at TEXT, origin TEXT, revoked_at TEXT);
CREATE INDEX IF NOT EXISTS idx_consents_phone ON consents (phone);
CREATE TABLE IF NOT EXISTS plots (
  id INTEGER PRIMARY KEY AUTOINCREMENT, producer_id INTEGER, name TEXT, geojson TEXT, area_ha REAL, crop TEXT,
  planting_date TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_plots_producer ON plots (producer_id);
CREATE TABLE IF NOT EXISTS verifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, name TEXT, code_hash TEXT, consents_json TEXT, text_version TEXT,
  created_at TEXT, expires_at TEXT, attempts INTEGER DEFAULT 0, used_at TEXT, ip TEXT);
CREATE INDEX IF NOT EXISTS idx_verif_phone ON verifications (phone, created_at);
CREATE INDEX IF NOT EXISTS idx_verif_ip ON verifications (ip, created_at);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, producer_id INTEGER, scope TEXT, created_at TEXT, expires_at TEXT, revoked_at TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS magic_links (
  token_hash TEXT PRIMARY KEY, producer_id INTEGER, scope TEXT, created_at TEXT, expires_at TEXT, used_at TEXT);
CREATE TABLE IF NOT EXISTS farms (
  producer_id INTEGER PRIMARY KEY, name TEXT, delivery_name TEXT, delivery_lat REAL, delivery_lon REAL);
CREATE TABLE IF NOT EXISTS seasons (
  id INTEGER PRIMARY KEY AUTOINCREMENT, producer_id INTEGER, plot_id INTEGER DEFAULT 0, crop TEXT, start_date TEXT,
  end_date TEXT, yield_t_ha REAL, notes TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_seasons_plot ON seasons (producer_id, plot_id);
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, producer_id INTEGER, plot_id INTEGER DEFAULT 0, season_id INTEGER, scene_date TEXT,
  source TEXT, ndvi_mean REAL, ndvi_median REAL, ndvi_std REAL, ndvi_p10 REAL, ndvi_p90 REAL, valid_fraction REAL,
  ndmi_mean REAL, area_ha REAL, engine TEXT, created_at TEXT,
  UNIQUE (producer_id, plot_id, scene_date, source));
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, event TEXT, subject_hash TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS links (
  token TEXT PRIMARY KEY, producer_id INTEGER, scope TEXT, created_at TEXT, expires_at TEXT);
CREATE TABLE IF NOT EXISTS processed_messages (
  id TEXT PRIMARY KEY, at TEXT);
CREATE TABLE IF NOT EXISTS reports (
  token TEXT PRIMARY KEY, producer_id INTEGER, created_at TEXT, expires_at TEXT, data_json TEXT);
"""

_FIELDS = ["phone", "channel", "lat", "lon", "crop", "planting_date", "consent", "lang",
           "source", "location_precision", "state", "active", "name"]


def connect() -> sqlite3.Connection:
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    for ddl in ("ALTER TABLE alert_log ADD COLUMN plot_id INTEGER DEFAULT 0",  # bancos criados antes dos vários talhões
                "ALTER TABLE producers ADD COLUMN name TEXT"):
        try:
            con.execute(ddl)
        except sqlite3.OperationalError:
            pass  # a coluna já existe
    return con


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def norm_phone(phone: str) -> str:
    """Telefone em um formato só (+ e dígitos): o WhatsApp manda '5565999990000', a cooperativa escreve '+55 65 99999-0000'."""
    return "+" + "".join(ch for ch in str(phone) if ch.isdigit())


def _to_producer(row: sqlite3.Row) -> Producer:
    d = dict(row)
    d["consent"] = bool(d["consent"])
    d["active"] = bool(d["active"])
    d.pop("created_at", None)
    return Producer(**d)


def create_producer(p: Producer) -> Producer:
    vals = [int(getattr(p, f)) if isinstance(getattr(p, f), bool) else getattr(p, f) for f in _FIELDS]
    vals[_FIELDS.index("phone")] = norm_phone(p.phone)
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
        row = con.execute("SELECT * FROM producers WHERE phone=?", (norm_phone(phone),)).fetchone()
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


def log_alert(producer_id: int, type_: str, sent_at: Optional[str] = None, plot_id: int = 0) -> None:
    with connect() as con:
        con.execute("INSERT INTO alert_log (producer_id, type, sent_at, plot_id) VALUES (?,?,?,?)",
                    (producer_id, type_, sent_at or _now(), plot_id))


def get_alert_log(producer_id: int, plot_id: Optional[int] = None) -> list[dict]:
    """Alertas já entregues. Com plot_id, só os daquele talhão (o silêncio de 72 h é por talhão); sem, todos do produtor
    (o limite diário e o semanal são por contato)."""
    q, args = "SELECT type, sent_at, plot_id FROM alert_log WHERE producer_id=?", [producer_id]
    if plot_id is not None:
        q += " AND plot_id=?"
        args.append(plot_id)
    with connect() as con:
        rows = con.execute(q, args).fetchall()
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


def create_report(producer_id: int, data: dict, ttl_days: int = 30) -> str:
    """Guarda o relatório detalhado e devolve o token (aleatório, impossível de adivinhar) que vai no link."""
    import secrets
    from datetime import timedelta
    token = secrets.token_urlsafe(16)
    now = datetime.now()
    with connect() as con:
        con.execute("INSERT INTO reports (token, producer_id, created_at, expires_at, data_json) VALUES (?,?,?,?,?)",
                    (token, producer_id, now.isoformat(timespec="seconds"),
                     (now + timedelta(days=ttl_days)).isoformat(timespec="seconds"),
                     json.dumps(data, ensure_ascii=False, default=str)))
    return token


def get_report(token: str) -> Optional[dict]:
    """Relatório pelo token; None se não existe ou expirou. Traz também producer_id e expires_at."""
    with connect() as con:
        row = con.execute("SELECT * FROM reports WHERE token=?", (token,)).fetchone()
    if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now():
        return None
    return {**json.loads(row["data_json"]), "_producer_id": row["producer_id"], "_expires_at": row["expires_at"],
            "_token": token}


# ---- registro de mensagens (entrada e saída) ----
def log_message(producer_id: Optional[int], phone: str, direction: str, channel: str, kind: str, content: str,
                type_: Optional[str] = None, confidence: Optional[str] = None, evidence: Optional[dict] = None,
                report_token: Optional[str] = None, provider_id: Optional[str] = None, state: str = "queued",
                error: Optional[str] = None) -> int:
    with connect() as con:
        cur = con.execute(
            "INSERT INTO messages (producer_id, phone, direction, channel, kind, type, content, confidence, evidence_json,"
            " report_token, provider_id, state, error, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (producer_id, norm_phone(phone), direction, channel, kind, type_, content, confidence,
             json.dumps(evidence, ensure_ascii=False, default=str) if evidence is not None else None, report_token,
             provider_id, state, error, _now()))
        return cur.lastrowid


def update_message(message_id: int, **fields) -> None:
    ok = {k: v for k, v in fields.items() if k in ("state", "provider_id", "error", "channel")}
    if ok:
        with connect() as con:
            con.execute(f"UPDATE messages SET {', '.join(f'{k}=?' for k in ok)} WHERE id=?", [*ok.values(), message_id])


def update_message_state_by_provider(provider_id: str, state: str, error: Optional[str] = None) -> int:
    """Status do provedor (enviada, entregue, lida, falhou). Só avança: 'lida' não volta a 'entregue'."""
    order = {"queued": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 9}
    with connect() as con:
        row = con.execute("SELECT id, state FROM messages WHERE provider_id=? ORDER BY id DESC LIMIT 1", (provider_id,)).fetchone()
        if not row or (order.get(state, 0) < order.get(row["state"], 0) and row["state"] != "failed"):
            return 0
        con.execute("UPDATE messages SET state=?, error=COALESCE(?, error) WHERE id=?", (state, error, row["id"]))
        return 1


def list_messages(producer_id: int, kind: Optional[str] = None, direction: Optional[str] = None, limit: int = 100) -> list[dict]:
    q, args = "SELECT * FROM messages WHERE producer_id=?", [producer_id]
    if kind:
        q += " AND kind=?"
        args.append(kind)
    if direction:
        q += " AND direction=?"
        args.append(direction)
    with connect() as con:
        rows = con.execute(q + " ORDER BY id DESC LIMIT ?", [*args, limit]).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["evidence"] = json.loads(d.pop("evidence_json")) if d.get("evidence_json") else None
        out.append(d)
    return out


def count_sent_today(producer_id: int, now: datetime, kinds=("alert",)) -> int:
    """Alertas enviados ao produtor no dia de `now` (para o limite diário)."""
    day = now.strftime("%Y-%m-%d")
    with connect() as con:
        marks = ",".join("?" * len(kinds))
        return con.execute(
            f"SELECT COUNT(*) FROM messages WHERE producer_id=? AND direction='out' AND kind IN ({marks}) "
            "AND substr(created_at,1,10)=? AND state!='failed'", (producer_id, *kinds, day)).fetchone()[0]


# ---- talhões (polígonos já validados por app.plots) ----
def create_plot(producer_id: int, name: str, geojson: dict, area_ha: float, crop: Optional[str] = None,
                planting_date: Optional[str] = None) -> dict:
    with connect() as con:
        cur = con.execute("INSERT INTO plots (producer_id, name, geojson, area_ha, crop, planting_date, created_at) VALUES (?,?,?,?,?,?,?)",
                          (producer_id, name, json.dumps(geojson), area_ha, crop, planting_date, _now()))
        row = con.execute("SELECT * FROM plots WHERE id=?", (cur.lastrowid,)).fetchone()
    return _plot(row)


def _plot(row) -> dict:
    d = dict(row)
    d["geojson"] = json.loads(d["geojson"])
    return d


def list_plots(producer_id: int) -> list[dict]:
    with connect() as con:
        return [_plot(r) for r in con.execute("SELECT * FROM plots WHERE producer_id=? ORDER BY area_ha DESC, id", (producer_id,)).fetchall()]


def get_plot(plot_id: int, producer_id: int) -> Optional[dict]:
    with connect() as con:
        row = con.execute("SELECT * FROM plots WHERE id=? AND producer_id=?", (plot_id, producer_id)).fetchone()
    return _plot(row) if row else None


def update_plot(plot_id: int, producer_id: int, **fields) -> Optional[dict]:
    """Altera nome, cultura, data de plantio, e/ou a geometria (geojson + area_ha). Só do dono do talhão."""
    allowed = {"name", "crop", "planting_date", "geojson", "area_ha"}
    fields = {k: (json.dumps(v) if k == "geojson" else v) for k, v in fields.items() if k in allowed}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        with connect() as con:
            con.execute(f"UPDATE plots SET {sets} WHERE id=? AND producer_id=?", [*fields.values(), plot_id, producer_id])
    return get_plot(plot_id, producer_id)


def delete_plot(plot_id: int, producer_id: int) -> int:
    with connect() as con:
        return con.execute("DELETE FROM plots WHERE id=? AND producer_id=?", (plot_id, producer_id)).rowcount


# ---- contatos (sucessor) ----
def add_contact(producer_id: int, phone: str, role: str = "sucessor") -> dict:
    phone = norm_phone(phone)
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO contacts (producer_id, phone, role, state, created_at) VALUES (?,?,?,?,?)",
                    (producer_id, phone, role, "AGUARDA_SIM", _now()))
        row = con.execute("SELECT * FROM contacts WHERE phone=?", (phone,)).fetchone()
    return dict(row)


def get_contact_by_phone(phone: str) -> Optional[dict]:
    with connect() as con:
        row = con.execute("SELECT * FROM contacts WHERE phone=?", (norm_phone(phone),)).fetchone()
    return dict(row) if row else None


def set_contact_state(phone: str, state: str) -> None:
    with connect() as con:
        con.execute("UPDATE contacts SET state=?, consent_at=CASE WHEN ?='ATIVO' THEN ? ELSE consent_at END WHERE phone=?",
                    (state, state, _now(), norm_phone(phone)))


def remove_contact(producer_id: int, phone: str) -> bool:
    """O produtor retira o segundo contato: deixa de receber e o consentimento dele é revogado."""
    phone = norm_phone(phone)
    with connect() as con:
        n = con.execute("UPDATE contacts SET state='SAIU' WHERE producer_id=? AND phone=? AND state!='SAIU'", (producer_id, phone)).rowcount
    if n:
        revoke_consents(phone)
    return n == 1


def list_contacts(producer_id: int, only_active: bool = False) -> list[dict]:
    q = "SELECT * FROM contacts WHERE producer_id=?" + (" AND state='ATIVO'" if only_active else "")
    with connect() as con:
        return [dict(r) for r in con.execute(q + " ORDER BY id", (producer_id,)).fetchall()]


# ---- consentimentos (finalidade, versão do texto, origem, revogação) ----
def record_consents(phone: str, producer_id: Optional[int], purposes: list[str], text_version: str, origin: str) -> None:
    phone = norm_phone(phone)
    with connect() as con:
        for purpose in purposes:
            con.execute("INSERT INTO consents (producer_id, phone, purpose, text_version, granted_at, origin) VALUES (?,?,?,?,?,?)",
                        (producer_id, phone, purpose, text_version, _now(), origin))


def revoke_consents(phone: str) -> int:
    with connect() as con:
        return con.execute("UPDATE consents SET revoked_at=? WHERE phone=? AND revoked_at IS NULL", (_now(), norm_phone(phone))).rowcount


def list_consents(phone: str) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM consents WHERE phone=? ORDER BY id", (norm_phone(phone),)).fetchall()]


def has_consent(phone: str, purpose: str = "mensagens") -> bool:
    with connect() as con:
        return con.execute("SELECT 1 FROM consents WHERE phone=? AND purpose=? AND revoked_at IS NULL",
                           (norm_phone(phone), purpose)).fetchone() is not None


# ---- links de uso do histórico (somente leitura) ----
def create_link(producer_id: int, scope: str, ttl_days: int = 30) -> str:
    import secrets
    from datetime import timedelta
    token = secrets.token_urlsafe(16)
    now = datetime.now()
    with connect() as con:
        con.execute("INSERT INTO links (token, producer_id, scope, created_at, expires_at) VALUES (?,?,?,?,?)",
                    (token, producer_id, scope, now.isoformat(timespec="seconds"),
                     (now + timedelta(days=ttl_days)).isoformat(timespec="seconds")))
    return token


def get_link(token: str, scope: str) -> Optional[dict]:
    with connect() as con:
        row = con.execute("SELECT * FROM links WHERE token=? AND scope=?", (token, scope)).fetchone()
    if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now():
        return None
    return dict(row)


def seen_message(message_id: str) -> bool:
    """True se este id de mensagem (webhook) já foi processado; senão registra e devolve False."""
    with connect() as con:
        try:
            con.execute("INSERT INTO processed_messages (id, at) VALUES (?, ?)", (message_id, _now()))
            return False
        except sqlite3.IntegrityError:
            return True


def delete_producer(producer_id: int) -> dict:
    """LGPD: apaga o produtor e tudo que é dele (análises, alertas, relatórios, escalonamentos e a pasta de dados)."""
    import hashlib
    import shutil
    counts = {}
    with connect() as con:
        row = con.execute("SELECT phone FROM producers WHERE id=?", (producer_id,)).fetchone()
        phones = [row["phone"]] if row else []
        phones += [r["phone"] for r in con.execute("SELECT phone FROM contacts WHERE producer_id=?", (producer_id,)).fetchall()]
        for t in ("analyses", "alert_log", "escalations", "reports", "messages", "links", "contacts", "consents", "plots",
                  "sessions", "magic_links", "farms", "seasons", "observations"):
            counts[t] = con.execute(f"DELETE FROM {t} WHERE producer_id=?", (producer_id,)).rowcount
        for ph in phones:  # consentimentos e mensagens sem produtor associado, do mesmo número
            counts["consents"] += con.execute("DELETE FROM consents WHERE phone=?", (ph,)).rowcount
            counts["messages"] += con.execute("DELETE FROM messages WHERE phone=?", (ph,)).rowcount
            counts["verifications"] = counts.get("verifications", 0) + con.execute("DELETE FROM verifications WHERE phone=?", (ph,)).rowcount
        counts["producers"] = con.execute("DELETE FROM producers WHERE id=?", (producer_id,)).rowcount
        if counts["producers"]:  # o mínimo que se guarda: que houve a exclusão, sem telefone nem dado pessoal (só um hash)
            con.execute("INSERT INTO audit_log (at, event, subject_hash, detail) VALUES (?,?,?,?)",
                        (_now(), "produtor_excluido", hashlib.sha256(phones[0].encode()).hexdigest()[:16], json.dumps(counts)))
    work = config.work_root() / str(producer_id)
    counts["pasta_work"] = int(work.exists())
    shutil.rmtree(work, ignore_errors=True)
    for d in config.work_root().glob(f"{producer_id}-p*"):  # um recorte de dados por talhão
        counts["pasta_work"] += 1
        shutil.rmtree(d, ignore_errors=True)
    return counts


def backup_to(dest) -> None:
    """Cópia consistente do banco (usa a API de backup do SQLite; seguro com o servidor rodando)."""
    with connect() as src:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
        finally:
            out.close()


def purge_expired_reports() -> int:
    with connect() as con:
        cur = con.execute("DELETE FROM reports WHERE expires_at < ?", (datetime.now().isoformat(timespec="seconds"),))
        return cur.rowcount


def reset_all() -> None:
    """Limpa tudo (usado pelo botão 'reiniciar demo' do simulador)."""
    with connect() as con:
        for t in ("producers", "analyses", "alert_log", "cache", "escalations", "reports", "messages", "contacts",
                  "consents", "links", "audit_log", "processed_messages", "plots", "verifications", "sessions",
                  "magic_links", "farms", "seasons", "observations"):
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
