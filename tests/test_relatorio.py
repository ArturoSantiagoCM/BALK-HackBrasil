"""Relatório detalhado: o link depois da mensagem, a página, as imagens, a conta mostrada e a segurança do link."""
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app, report_limiter
from app.models import Producer
from app.service import analyze_producer

client = TestClient(app)
NOW = datetime(2026, 11, 27, 10, 0)


@pytest.fixture(autouse=True)
def _limpa_limite():
    report_limiter.reset()


def _produtor(**kw):
    base = dict(phone="+5500900000777", lat=-23.5874, lon=-46.6576, crop="soja", planting_date="2026-07-25", consent=True,
                state="ATIVO", source="t", channel="whatsapp")
    base.update(kw)
    return db.create_producer(Producer(**base))


def _token(url: str) -> str:
    return url.rsplit("/r/", 1)[1]


def test_toda_mensagem_do_whatsapp_termina_com_o_link_do_relatorio():
    p = _produtor()
    res = analyze_producer(p.id, full=True, now=NOW)
    assert res["report_url"].startswith("http://localhost:8000/r/")
    assert len(res["messages"]) >= 2  # relatório + ao menos um alerta
    for m in res["messages"]:
        assert m["text"].rstrip().endswith(res["report_url"])
        assert "Detalhes, mapas e o porquê:" in m["text"]
    rel = [m for m in res["messages"] if m["kind"] == "report"][0]
    assert rel["media_url"] == res["report_url"] + "/img/mapa.png"


def test_sms_nao_leva_link_por_padrao_e_so_com_a_chave_e_se_couber(monkeypatch):
    p = _produtor(channel="sms", phone="+5500900000778")
    res = analyze_producer(p.id, full=True, now=NOW)
    assert res["report_url"] and all("http" not in m["text"] and len(m["text"]) <= 160 for m in res["messages"])
    monkeypatch.setenv("SMS_INCLUDE_LINK", "1")
    from app.message import with_link
    assert with_link("BALK: teste", "sms", "pt", "http://x/r/abc") == "BALK: teste http://x/r/abc"
    longo = "x" * 150
    assert with_link(longo, "sms", "pt", "http://x/r/abc") == longo  # não cabe: fica sem link


def test_pagina_do_relatorio_tem_dados_mapas_conta_e_porque():
    p = _produtor()
    res = analyze_producer(p.id, full=True, now=NOW)
    tok = _token(res["report_url"])
    r = client.get(f"/r/{tok}")
    assert r.status_code == 200
    html = r.text
    for trecho in ["Os dados que coletamos", "Mapas da sua área", "Por que estas notas", "Alertas e por que foram enviados",
                   "Como o BALK pensou", "Não substitui um engenheiro agrônomo", "SIMULADA",  # dados simulados avisados
                   "Open-Meteo", "Embrapa", "Premissa da equipe", "Conferido em fonte técnica", "Fator que mais limita",
                   "Limite da regra", "Valor previsto", "atende", "noindex"]:
        assert trecho in html, trecho
    assert "+5500900000777" not in html  # nunca mostra o telefone
    assert "-23.5874" not in html and "-23.59" in html  # coordenadas só arredondadas (~1 km)
    for k in ("ndvi", "slope", "zonas", "fatores", "clima", "modelo"):
        assert f"/r/{tok}/img/{k}.png" in html
    for k in ("ndvi", "slope", "zonas", "fatores", "clima", "modelo", "mapa"):
        img = client.get(f"/r/{tok}/img/{k}.png")
        assert img.status_code == 200 and img.content[:4] == b"\x89PNG", k


def test_cabecalhos_de_seguranca_do_relatorio():
    p = _produtor()
    tok = _token(analyze_producer(p.id, full=True, now=NOW)["report_url"])
    h = client.get(f"/r/{tok}").headers
    assert "noindex" in h["x-robots-tag"] and "default-src 'none'" in h["content-security-policy"]
    assert h["referrer-policy"] == "no-referrer" and h["x-content-type-options"] == "nosniff" and "private" in h["cache-control"]


def test_baixar_gera_um_unico_arquivo_com_as_imagens_dentro():
    p = _produtor()
    tok = _token(analyze_producer(p.id, full=True, now=NOW)["report_url"])
    r = client.get(f"/r/{tok}/baixar")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.text.count("data:image/png;base64,") >= 6 and "src=\"/r/" not in r.text


def test_token_invalido_expirado_e_inexistente_dao_o_mesmo_404():
    assert client.get("/r/curto").status_code == 404
    assert client.get("/r/" + "a" * 22).status_code == 404
    assert client.get("/r/" + "a" * 22 + "/img/ndvi.png").status_code == 404
    p = _produtor()
    tok = _token(analyze_producer(p.id, full=True, now=NOW)["report_url"])
    with db.connect() as con:
        con.execute("UPDATE reports SET expires_at=?", ((datetime.now() - timedelta(days=1)).isoformat(),))
    assert client.get(f"/r/{tok}").status_code == 404
    assert db.purge_expired_reports() == 1


def test_nome_de_imagem_malicioso_e_recusado():
    p = _produtor()
    tok = _token(analyze_producer(p.id, full=True, now=NOW)["report_url"])
    for nome in ("..%2f..%2fbalk.db", "ndvi.png.exe", "NDVI.png", "a" * 40 + ".png", "x.html"):
        assert client.get(f"/r/{tok}/img/{nome}").status_code in (404, 422)


def test_limite_de_requisicoes_na_pagina_do_relatorio():
    codigos = [client.get("/r/" + "b" * 22).status_code for _ in range(62)]
    assert codigos.count(429) >= 1 and codigos[0] == 404


def test_tokens_sao_unicos_e_longos():
    p = _produtor()
    toks = {_token(analyze_producer(p.id, full=True, now=NOW)["report_url"]) for _ in range(3)}
    assert len(toks) == 3 and all(len(t) >= 20 and re.fullmatch(r"[A-Za-z0-9_-]+", t) for t in toks)


def test_relatorio_so_de_municipio_abre_sem_mapas_e_avisa():
    p = _produtor(location_precision="municipio", phone="+5500900000779")
    res = analyze_producer(p.id, full=True, now=NOW)
    r = client.get(f"/r/{_token(res['report_url'])}")
    assert r.status_code == 200 and "município" in r.text and "Mapas da sua área" not in r.text
    assert "Os dados que coletamos" in r.text and "Como o BALK pensou" in r.text


def test_alerta_do_dia_tambem_traz_o_link_e_o_porque():
    p = _produtor()
    res = analyze_producer(p.id, full=False, now=NOW)
    assert res["alerts"] and res["report_url"]
    page = client.get(f"/r/{_token(res['report_url'])}").text  # imagens geradas na primeira visita
    assert "Alertas e por que foram enviados" in page and "Mapas da sua área" in page


def test_ceu_que_explica_a_nota_bate_com_a_nota_enviada():
    p = _produtor()
    res = analyze_producer(p.id, full=True, now=NOW)
    data = db.get_report(_token(res["report_url"]))
    for c, v in zip(data["culturas"], res["ranking"]):
        assert c["crop"] == v["crop"] and c["nota"] == v["score"]
        notas = [(f["nota"], f["peso"]) for f in c["fatores"] if f["nota"] is not None]
        conta = round(100 * sum(n * w for n, w in notas) / sum(w for _, w in notas))
        if any(n == 0 for n, _ in notas):
            conta = min(conta, 40)
        assert conta == c["nota"]
        assert all(f["fonte_titulo"] for f in c["fatores"])  # toda faixa mostra de onde vem
