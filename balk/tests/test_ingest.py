from datetime import date

import pytest

from app import config, db
from app.ingest.conversation import (ASK_CROP, ASK_DATE, CONSENT, handle_message, match_crop, parse_date,
                                     parse_sms)
from app.ingest.csv_import import ingest_rows, parse_csv_text

HOJE = date(2026, 11, 27)


def test_conversa_completa_ate_ativo_com_consentimento():
    r = handle_message("55119", "oi")
    assert r.text == CONSENT and not r.became_active
    assert handle_message("55119", "talvez").text == CONSENT  # só avança com SIM
    handle_message("55119", "SIM")
    r = handle_message("55119", "", location=(-12.54, -55.72))
    assert r.text == ASK_CROP
    assert handle_message("55119", "Soja").text == ASK_DATE
    r = handle_message("55119", "20/10", today=HOJE)
    assert r.became_active
    p = db.get_producer_by_phone("55119")
    assert p.consent and p.state == "ATIVO" and p.crop == "soja" and p.planting_date == "2026-10-20"
    assert p.location_precision == "ponto" and p.id in [x.id for x in db.list_active()]


def test_validacoes_pedem_de_novo():
    handle_message("1", "oi"), handle_message("1", "sim")
    assert "entender o local" in handle_message("1", "", location=(80.0, -55.0)).text  # fora das Américas
    assert "entender o local" in handle_message("1", "xyzzy").text
    handle_message("1", "", location=(-12.5, -55.7))
    assert "Não reconheci" in handle_message("1", "batata").text
    handle_message("1", "não sei")
    assert "inválida" in handle_message("1", "31/12/2030", today=HOJE).text
    assert "inválida" in handle_message("1", "ontem", today=HOJE).text
    assert handle_message("1", "não sei").became_active
    assert db.get_producer_by_phone("1").crop is None


def test_coordenadas_por_texto_e_municipio():
    handle_message("2", "oi"), handle_message("2", "sim")
    handle_message("2", "-12,54 , -55,72")
    p = db.get_producer_by_phone("2")
    assert (p.lat, p.lon) == (-12.54, -55.72) and p.location_precision == "ponto"
    handle_message("3", "oi"), handle_message("3", "sim")
    r = handle_message("3", "Sorriso")
    assert "só consigo enviar alertas de clima" in r.text
    assert db.get_producer_by_phone("3").location_precision == "municipio"


def test_sair_desativa_a_qualquer_momento_e_pode_voltar():
    handle_message("4", "oi"), handle_message("4", "sim")
    handle_message("4", "SAIR")
    p = db.get_producer_by_phone("4")
    assert not p.active and not p.consent and p not in db.list_active()
    assert handle_message("4", "oi").text == CONSENT
    assert db.get_producer_by_phone("4").active


def test_respostas_1_e_2_no_estado_ativo():
    for t in ("oi", "sim"):
        handle_message("5", t)
    handle_message("5", "", location=(-12.5, -55.7)), handle_message("5", "milho"), handle_message("5", "não sei")
    assert "Registrado" in handle_message("5", "1").text
    assert "agrônomo" in handle_message("5", "2").text
    assert len(db.list_escalations()) == 1


# ---- SMS ----
@pytest.mark.parametrize("txt,esperado", [
    ("BALK soja 20/10 Sorriso MT", {"crop": "soja", "date": "20/10", "municipio": "Sorriso", "uf": "MT"}),
    ("balk sojs 20/10 sorriso mt", {"crop": "soja", "date": "20/10", "municipio": "sorriso", "uf": "MT"}),
    ("BALKK feijao 5/3 Passo Fundo RS", {"crop": "feijao", "date": "5/3", "municipio": "Passo Fundo", "uf": "RS"}),
    ("BALK café 01/04 Londrina PR", {"crop": "cafe", "date": "01/04", "municipio": "Londrina", "uf": "PR"}),
])
def test_parse_sms_completo_e_com_erros_de_digitacao(txt, esperado):
    d = parse_sms(txt)
    assert d["missing"] == []
    for k, v in esperado.items():
        assert d[k] == v


@pytest.mark.parametrize("txt,falta", [
    ("BALK milho Sorriso MT", "data"), ("BALK 20/10 Sorriso MT", "cultura"), ("BALK soja 20/10", "municipio"),
])
def test_parse_sms_devolve_o_campo_que_faltou(txt, falta):
    assert parse_sms(txt)["missing"] == [falta]


def test_sms_cadastro_ate_ativo():
    r = handle_message("+5565", "BALK soja 20/10 Sorriso MT", channel="sms", today=HOJE)
    assert "SIM" in r.text and not r.became_active
    p = db.get_producer_by_phone("+5565")
    assert p.state == "AGUARDA_SIM" and not p.consent and p.location_precision == "municipio"
    r = handle_message("+5565", "SIM", channel="sms")
    assert r.became_active
    p = db.get_producer_by_phone("+5565")
    assert p.consent and p.channel == "sms" and p.crop == "soja" and p.planting_date == "2026-10-20"
    assert "1" in handle_message("+5565", "2", channel="sms").text or db.list_escalations()
    assert len(db.list_escalations()) == 1
    handle_message("+5565", "SAIR", channel="sms")
    assert not db.get_producer_by_phone("+5565").active


def test_sms_pede_o_que_falta_e_municipio_desconhecido():
    r = handle_message("+55", "BALK soja Sorriso MT", channel="sms")
    assert "faltou data" in r.text and db.get_producer_by_phone("+55") is None
    assert "nao achei" in handle_message("+55", "BALK soja 20/10 Zzzzz XX", channel="sms", today=HOJE).text


def test_parse_date_e_match_crop():
    assert parse_date("5/3", HOJE) == "2026-03-05"
    assert parse_date("20/12", HOJE) == "2025-12-20"  # sem ano: última ocorrência passada
    assert parse_date("2026-10-01", HOJE) == "2026-10-01"
    with pytest.raises(ValueError):
        parse_date("2026-12-01", HOJE)
    assert match_crop("Feijão") == "feijao" and match_crop("hortaliça") == "hortalica" and match_crop("xyz") is None


# ---- CSV ----
def test_csv_de_exemplo_importa_5_produtores():
    text = (config.ROOT / "demo" / "coop.csv").read_text(encoding="utf-8")
    out = ingest_rows(parse_csv_text(text), today=HOJE)
    assert out["aceitos"] == 5 and out["erros"] == []
    ativos = db.list_active()
    assert len(ativos) == 5 and all(p.consent and p.source == "coop_demo" for p in ativos)
    assert ingest_rows(parse_csv_text(text), today=HOJE)["aceitos"] == 5 and len(db.list_active()) == 5  # idempotente


def test_csv_erros_por_linha():
    csv_text = ("telefone;lat;lon;cultura;data_plantio;canal;origem\n"
                "+550011100;-12,5;-55,7;soja;2026-10-01;whatsapp;coop\n"
                ";-12.5;-55.7;soja;2026-10-01;whatsapp;coop\n"
                "+550022200;abc;-55.7;soja;;;coop\n"
                "+550033300;60;10;soja;;;coop\n"
                "+550044400;-12.5;-55.7;batata;;;coop\n"
                "+550055500;-12.5;-55.7;milho;2031-01-01;;coop\n"
                "+550066600;-12.5;-55.7;milho;;fax;coop\n")
    out = ingest_rows(parse_csv_text(csv_text), today=HOJE)
    assert out["aceitos"] == 1
    assert [e["linha"] for e in out["erros"]] == [2, 3, 4, 5, 6, 7]
    assert "coordenadas" in out["erros"][2]["erro"] and "cultura" in out["erros"][3]["erro"]

