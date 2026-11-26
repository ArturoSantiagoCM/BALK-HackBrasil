"""Banco do site: verificação por código, sessões, links de uso único, propriedade, safras e observações.

Segredos nunca ficam em texto: código de verificação, token de sessão e token de link guardam só o hash.
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta
from statistics import mean, pstdev
from typing import Optional

from app import config
from app.db import _now, connect, norm_phone


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ---------------------------------------------------------------- verificação por código
def count_verifications(phone: Optional[str] = None, ip: Optional[str] = None, since: Optional[datetime] = None) -> int:
    q, args = "SELECT COUNT(*) FROM verifications WHERE created_at >= ?", [_iso(since or datetime.min)]
    if phone:
        q += " AND phone=?"
        args.append(norm_phone(phone))
    if ip:
        q += " AND ip=?"
        args.append(ip)
    with connect() as con:
        return con.execute(q, args).fetchone()[0]


def last_verification_at(phone: str) -> Optional[datetime]:
    with connect() as con:
        row = con.execute("SELECT created_at FROM verifications WHERE phone=? ORDER BY id DESC LIMIT 1", (norm_phone(phone),)).fetchone()
    return datetime.fromisoformat(row["created_at"]) if row else None


def create_verification(phone: str, name: str, code_hash: str, consents: list[str], text_version: str, ttl_min: int,
                        ip: str) -> int:
    now = datetime.now()
    with connect() as con:
        # um código novo invalida os anteriores ainda abertos
        con.execute("UPDATE verifications SET used_at=? WHERE phone=? AND used_at IS NULL", (_iso(now), norm_phone(phone)))
        cur = con.execute(
            "INSERT INTO verifications (phone, name, code_hash, consents_json, text_version, created_at, expires_at, ip) VALUES (?,?,?,?,?,?,?,?)",
            (norm_phone(phone), name, code_hash, json.dumps(consents), text_version, _iso(now), _iso(now + timedelta(minutes=ttl_min)), ip))
        return cur.lastrowid


def open_verification(phone: str) -> Optional[dict]:
    with connect() as con:
        row = con.execute("SELECT * FROM verifications WHERE phone=? AND used_at IS NULL ORDER BY id DESC LIMIT 1",
                          (norm_phone(phone),)).fetchone()
    if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now():
        return None
    return dict(row)


def bump_attempts(verification_id: int) -> int:
    with connect() as con:
        con.execute("UPDATE verifications SET attempts = attempts + 1 WHERE id=?", (verification_id,))
        return con.execute("SELECT attempts FROM verifications WHERE id=?", (verification_id,)).fetchone()[0]


def take_attempt(verification_id: int, max_attempts: int) -> bool:
    """Gasta UMA tentativa de forma atômica: só conta se ainda restam tentativas e o código não foi usado. Pedidos
    simultâneos não conseguem passar do limite (a checagem e o incremento são a mesma instrução)."""
    with connect() as con:
        return con.execute("UPDATE verifications SET attempts = attempts + 1 WHERE id=? AND attempts < ? AND used_at IS NULL",
                           (verification_id, max_attempts)).rowcount == 1


def purge_expired(verification_hours: int = 24, now: Optional[datetime] = None) -> dict:
    """Retenção curta: verificações (telefone, nome, IP) com mais de 24 h, sessões expiradas ou revogadas e links gastos ou vencidos."""
    now = now or datetime.now()
    limit = _iso(now - timedelta(hours=verification_hours))
    with connect() as con:
        return {
            "verificacoes": con.execute("DELETE FROM verifications WHERE created_at < ?", (limit,)).rowcount,
            "sessoes": con.execute("DELETE FROM sessions WHERE expires_at < ? OR (revoked_at IS NOT NULL AND revoked_at < ?)",
                                   (_iso(now), limit)).rowcount,
            "links": con.execute("DELETE FROM magic_links WHERE expires_at < ? OR used_at IS NOT NULL", (_iso(now),)).rowcount,
        }


def use_verification(verification_id: int) -> bool:
    """Marca como usado, uma única vez (o segundo uso do mesmo código falha)."""
    with connect() as con:
        return con.execute("UPDATE verifications SET used_at=? WHERE id=? AND used_at IS NULL", (_now(), verification_id)).rowcount == 1


# ---------------------------------------------------------------- sessões opacas
def create_session(producer_id: int, scope: str = "site", ttl_days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    with connect() as con:
        con.execute("INSERT INTO sessions (token_hash, producer_id, scope, created_at, expires_at, last_seen) VALUES (?,?,?,?,?,?)",
                    (_hash(token), producer_id, scope, _iso(now), _iso(now + timedelta(days=ttl_days)), _iso(now)))
    return token


def get_session(token: str) -> Optional[dict]:
    if not token:
        return None
    with connect() as con:
        row = con.execute("SELECT * FROM sessions WHERE token_hash=?", (_hash(token),)).fetchone()
        if not row or row["revoked_at"] or datetime.fromisoformat(row["expires_at"]) < datetime.now():
            return None
        con.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (_now(), row["token_hash"]))
    return dict(row)


def revoke_session(token: str) -> None:
    with connect() as con:
        con.execute("UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL", (_now(), _hash(token)))


def revoke_all_sessions(producer_id: int) -> int:
    with connect() as con:
        return con.execute("UPDATE sessions SET revoked_at=? WHERE producer_id=? AND revoked_at IS NULL", (_now(), producer_id)).rowcount


# ---------------------------------------------------------------- links de uso único (WhatsApp -> site)
def create_magic_link(producer_id: int, scope: str = "map", ttl_min: int = 30) -> str:
    token = secrets.token_urlsafe(24)
    now = datetime.now()
    with connect() as con:
        con.execute("INSERT INTO magic_links (token_hash, producer_id, scope, created_at, expires_at) VALUES (?,?,?,?,?)",
                    (_hash(token), producer_id, scope, _iso(now), _iso(now + timedelta(minutes=ttl_min))))
    return token


def consume_magic_link(token: str) -> Optional[dict]:
    """Consome o link. Só funciona uma vez e dentro da validade; a segunda tentativa devolve None."""
    h = _hash(token)
    with connect() as con:
        row = con.execute("SELECT * FROM magic_links WHERE token_hash=?", (h,)).fetchone()
        if not row or datetime.fromisoformat(row["expires_at"]) < datetime.now():
            return None
        if con.execute("UPDATE magic_links SET used_at=? WHERE token_hash=? AND used_at IS NULL", (_now(), h)).rowcount != 1:
            return None
    return dict(row)


# ---------------------------------------------------------------- propriedade e destino de entrega
def save_farm(producer_id: int, name: Optional[str] = None, delivery_name: Optional[str] = None,
              delivery_lat: Optional[float] = None, delivery_lon: Optional[float] = None) -> dict:
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO farms (producer_id) VALUES (?)", (producer_id,))
        con.execute("UPDATE farms SET name=COALESCE(?, name), delivery_name=?, delivery_lat=?, delivery_lon=? WHERE producer_id=?",
                    (name, delivery_name, delivery_lat, delivery_lon, producer_id))
        row = con.execute("SELECT * FROM farms WHERE producer_id=?", (producer_id,)).fetchone()
    return dict(row)


def get_farm(producer_id: int) -> dict:
    with connect() as con:
        row = con.execute("SELECT * FROM farms WHERE producer_id=?", (producer_id,)).fetchone()
    return dict(row) if row else {"producer_id": producer_id, "name": None, "delivery_name": None, "delivery_lat": None, "delivery_lon": None}


# ---------------------------------------------------------------- safras e observações por talhão
def ensure_season(producer_id: int, plot_id: int, crop: Optional[str], planting_date: Optional[str]) -> Optional[dict]:
    """A safra aberta do talhão. Sem cultura ou sem data de plantio não há safra. Mesma cultura com data corrigida só
    ajusta a data; cultura diferente fecha a safra anterior e abre outra."""
    if not crop or not planting_date:
        return None
    with connect() as con:
        cur = con.execute("SELECT * FROM seasons WHERE producer_id=? AND plot_id=? AND end_date IS NULL ORDER BY id DESC LIMIT 1",
                          (producer_id, plot_id)).fetchone()
        if cur and cur["crop"] == crop:
            if cur["start_date"] != planting_date:
                con.execute("UPDATE seasons SET start_date=? WHERE id=?", (planting_date, cur["id"]))
            return dict(con.execute("SELECT * FROM seasons WHERE id=?", (cur["id"],)).fetchone())
        if cur:
            con.execute("UPDATE seasons SET end_date=? WHERE id=?", (planting_date, cur["id"]))
        sid = con.execute("INSERT INTO seasons (producer_id, plot_id, crop, start_date, created_at) VALUES (?,?,?,?,?)",
                          (producer_id, plot_id, crop, planting_date, _now())).lastrowid
        return dict(con.execute("SELECT * FROM seasons WHERE id=?", (sid,)).fetchone())


def close_season(season_id: int, producer_id: int, yield_t_ha: Optional[float], end_date: Optional[str] = None,
                 notes: Optional[str] = None) -> bool:
    with connect() as con:
        return con.execute("UPDATE seasons SET end_date=?, yield_t_ha=?, notes=? WHERE id=? AND producer_id=?",
                           (end_date or datetime.now().strftime("%Y-%m-%d"), yield_t_ha, notes, season_id, producer_id)).rowcount == 1


def open_seasons(producer_id: int) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM seasons WHERE producer_id=? AND end_date IS NULL ORDER BY id", (producer_id,)).fetchall()]


def save_observation(producer_id: int, plot_id: int, season_id: Optional[int], stats, source: str) -> bool:
    """Uma observação por cena nova: repetir a análise sobre a mesma cena NÃO cria registro (idempotente). True se criou."""
    if not stats or not stats.scene_date or stats.ndvi_mean is None:
        return False
    with connect() as con:
        return con.execute(
            "INSERT OR IGNORE INTO observations (producer_id, plot_id, season_id, scene_date, source, ndvi_mean, ndvi_median, ndvi_std,"
            " ndvi_p10, ndvi_p90, valid_fraction, ndmi_mean, area_ha, engine, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (producer_id, plot_id, season_id, stats.scene_date, source, stats.ndvi_mean, stats.ndvi_median, stats.ndvi_std,
             stats.ndvi_p10, stats.ndvi_p90, stats.valid_fraction, stats.ndmi_mean, stats.area_ha, stats.engine, _now())).rowcount == 1


def observation_history(producer_id: int, plot_id: int, crop: Optional[str], cycle_day: Optional[int], current_season_id: Optional[int],
                        window_days: int = 15, recent_days: int = 60, now: Optional[datetime] = None) -> dict:
    """Referência de NDVI para o alerta de vigor, na ordem: (1) safras anteriores do MESMO talhão e cultura, na mesma fase do ciclo
    (confiança média); (2) a série recente da safra atual (confiança baixa). Devolve {} se não há nada utilizável."""
    now = now or datetime.now()
    with connect() as con:
        prev = []
        if crop and cycle_day is not None:
            rows = con.execute(
                "SELECT o.ndvi_mean AS v, o.scene_date AS d, s.start_date AS s0 FROM observations o JOIN seasons s ON s.id = o.season_id "
                "WHERE o.producer_id=? AND o.plot_id=? AND s.crop=? AND s.id != COALESCE(?, -1)", (producer_id, plot_id, crop, current_season_id)).fetchall()
            for r in rows:
                day = (datetime.fromisoformat(r["d"]) - datetime.fromisoformat(r["s0"])).days
                if abs(day - cycle_day) <= window_days:
                    prev.append(r["v"])
        recent = []
        if current_season_id:
            since = (now - timedelta(days=recent_days)).strftime("%Y-%m-%d")
            today = now.strftime("%Y-%m-%d")
            recent = [r["ndvi_mean"] for r in con.execute(
                "SELECT ndvi_mean FROM observations WHERE season_id=? AND scene_date>=? AND scene_date<? ORDER BY scene_date",
                (current_season_id, since, today)).fetchall()]
    if len(prev) >= 3:
        return {"mean": mean(prev), "std": max(pstdev(prev), 0.03), "n": len(prev), "referencia": "historico"}
    if len(recent) >= 4:
        return {"mean": mean(recent), "std": max(pstdev(recent), 0.03), "n": len(recent), "referencia": "serie_recente"}
    return {}


def seasons_overview(producer_id: int) -> list[dict]:
    """Por talhão e safra: cultura, datas, produtividade informada e o que o satélite viu (pico, média, nº de observações)."""
    with connect() as con:
        plots = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM plots WHERE producer_id=?", (producer_id,)).fetchall()}
        out = []
        for s in con.execute("SELECT * FROM seasons WHERE producer_id=? ORDER BY plot_id, start_date DESC", (producer_id,)).fetchall():
            obs = con.execute("SELECT scene_date, ndvi_mean FROM observations WHERE season_id=? ORDER BY scene_date", (s["id"],)).fetchall()
            vals = [o["ndvi_mean"] for o in obs]
            peak = max(obs, key=lambda o: o["ndvi_mean"]) if obs else None
            out.append({**dict(s), "plot_name": plots.get(s["plot_id"], "Lavoura"), "n_observacoes": len(obs),
                        "ndvi_pico": round(peak["ndvi_mean"], 2) if peak else None, "data_pico": peak["scene_date"] if peak else None,
                        "ndvi_medio": round(mean(vals), 2) if vals else None,
                        "serie": [(o["scene_date"], round(o["ndvi_mean"], 3)) for o in obs]})
    return out
