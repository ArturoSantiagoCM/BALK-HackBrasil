"""M1: POST /ingest/producers aceita JSON ou CSV (telefone, lat, lon, cultura, data_plantio, canal, origem)."""
import csv
import io
from datetime import date
from typing import Optional

from app import db
from app.ingest.conversation import match_crop, norm, parse_date, valid_coords
from app.models import Producer

COLUMNS = ["telefone", "lat", "lon", "cultura", "data_plantio", "canal", "origem", "consentimento"]


def parse_csv_text(text: str) -> list[dict]:
    """CSV com vírgula ou ponto e vírgula; cabeçalhos em minúsculas, sem acento."""
    text = text.lstrip("﻿")
    sample = text.splitlines()[0] if text.strip() else ""
    delim = ";" if sample.count(";") > sample.count(",") else ","
    rows = []
    for r in csv.DictReader(io.StringIO(text), delimiter=delim):
        rows.append({norm(k): (v or "").strip() for k, v in r.items() if k})
    return rows


def _validate(row: dict, today: Optional[date]) -> Producer:
    phone = "".join(ch for ch in row.get("telefone", "") if ch.isdigit() or ch == "+")
    if len(phone.replace("+", "")) < 8:
        raise ValueError("telefone ausente ou curto demais")
    try:
        lat, lon = float(row.get("lat", "").replace(",", ".")), float(row.get("lon", "").replace(",", "."))
    except ValueError:
        raise ValueError("lat/lon inválidos")
    if not valid_coords(lat, lon):
        raise ValueError("coordenadas fora das Américas")
    crop = None
    if row.get("cultura"):
        crop = match_crop(row["cultura"])
        if crop is None:
            raise ValueError(f"cultura desconhecida: {row['cultura']}")
    planting = None
    if row.get("data_plantio"):
        try:
            planting = parse_date(row["data_plantio"], today)
        except ValueError as e:
            raise ValueError(f"data_plantio inválida ({e})")
    channel = norm(row.get("canal", "")) or "whatsapp"
    if channel not in ("whatsapp", "sms"):
        raise ValueError("canal deve ser whatsapp ou sms")
    if norm(row.get("consentimento", "sim")) not in ("sim", "s", "true", "1", "yes"):
        raise ValueError("sem consentimento declarado pela cooperativa")
    return Producer(phone=phone, channel=channel, lat=lat, lon=lon, crop=crop, planting_date=planting,
                    consent=True, source=row.get("origem") or "csv", location_precision="ponto", state="ATIVO",
                    active=True)


def ingest_rows(rows: list[dict], today: Optional[date] = None) -> dict:
    """Valida cada linha. Devolve quantas foram aceitas e os erros por linha (a primeira linha de dados é a 1)."""
    accepted, errors = [], []
    for i, raw in enumerate(rows, start=1):
        row = {norm(k): (str(v) if v is not None else "").strip() for k, v in raw.items()}
        # aceita também as chaves em inglês do contrato Producer
        row.setdefault("telefone", row.get("phone", ""))
        row.setdefault("cultura", row.get("crop", ""))
        row.setdefault("data_plantio", row.get("planting_date", ""))
        row.setdefault("canal", row.get("channel", ""))
        row.setdefault("origem", row.get("source", ""))
        try:
            p = _validate(row, today)
        except ValueError as e:
            errors.append({"linha": i, "erro": str(e)})
            continue
        existing = db.get_producer_by_phone(p.phone)
        if existing:  # idempotente: reimportar atualiza
            p = db.update_producer(existing.id, **p.model_dump(exclude={"id", "phone"}))
        else:
            p = db.create_producer(p)
        accepted.append(p.id)
    return {"aceitos": len(accepted), "erros": errors, "ids": accepted}
