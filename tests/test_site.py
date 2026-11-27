"""Site: cadastro com código pelo WhatsApp, sessão, talhões, link de uso único, vários talhões e histórico por safra."""
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import auth, db, db_site, security, site_api
from app.channels import OUTBOX
from app.data import simulated
from app.ingest.conversation import handle_message
from app.main import app
from app.models import Producer, Weather
from app.service import analyze_producer, run_daily
from tests.conftest import NOW
from tests.test_talhoes import quadrado

TEL = "65 99999-0001"
TEL_N = "+5565999990001"  # o site põe o 55 em número com DDD e sem código do país
LAT, LON = -23.5874, -46.6576


@pytest.fixture(autouse=True)
def limpo(monkeypatch):
    OUTBOX.clear()
    for lim in (site_api.signup_limiter, site_api.verify_limiter, site_api.geocode_limiter, site_api.link_limiter,
                site_api.invite_limiter, site_api.report_limiter_site):
        lim.reset()
    monkeypatch.setattr(auth, "COOLDOWN_S", 0)  # os testes pedem vários códigos seguidos (o limite de 60 s tem teste próprio)
    monkeypatch.setattr("app.delivery.BACKOFF_S", 0)


def novo_cliente() -> TestClient:
    return TestClient(app)


def pedir_codigo(c, tel=TEL, nome="Maria", dados=True, msgs=True):
    return c.post("/api/signup/start", json={"name": nome, "phone": tel, "consent_dados": dados, "consent_mensagens": msgs})


def ultimo_codigo() -> str:
    for m in reversed(OUTBOX):
        achou = re.search(r"\b(\d{6})\b", m["text"])
        if achou and "verificação" in m["text"]:
            return achou.group(1)
    raise AssertionError("nenhum código enviado")


def entrar(tel=TEL, nome="Maria") -> TestClient:
    c = novo_cliente()
    assert pedir_codigo(c, tel, nome).status_code == 200
    r = c.post("/api/signup/verify", json={"phone": tel, "code": ultimo_codigo()})
    assert r.status_code == 200, r.text
    return c


# ---------------------------------------------------------------- verificação por código
def test_config_publica_traz_consentimento_versionado_mapa_e_limites():
    r = novo_cliente().get("/api/config").json()
    assert r["consentimento"]["versao"] == "v0" and r["consentimento"]["mensagens"] and r["consentimento"]["dados_localizacao"]
    assert "{z}" in r["mapa"]["url"] and r["limites"]["area_min_ha"] > 0 and "soja" in r["culturas"]


def test_mapa_tem_satelite_sentinel_relevo_ruas_rotulos_e_sombreado_e_maptiler_entra_primeiro_com_chave(monkeypatch):
    monkeypatch.delenv("MAPTILER_KEY", raising=False)
    c = novo_cliente()
    m = c.get("/api/config").json()["mapa"]
    ids = [(x["id"], x["tipo"]) for x in m["layers"]]
    assert ids == [("satelite", "base"), ("sentinel", "base"), ("relevo", "base"), ("ruas", "base"), ("nomes", "overlay"), ("sombreado", "dem")]
    assert "arcgisonline" in m["url"] and "Esri" in m["attribution"]  # o satélite abre primeiro, sem chave
    assert all(x["attribution"] and "{z}" in x["url"] and x["max_zoom"] for x in m["layers"])  # toda camada com atribuição
    csp = c.get("/app/mapa.html").headers["content-security-policy"]
    for host in ("server.arcgisonline.com", "tiles.maps.eox.at", "tile.opentopomap.org", "tile.openstreetmap.org", "s3.amazonaws.com"):
        assert f"https://{host}" in csp, host  # o navegador pode buscar todas as camadas (e só elas)
    monkeypatch.setenv("MAPTILER_KEY", "chave-de-teste")
    c = novo_cliente()
    m = c.get("/api/config").json()["mapa"]
    assert m["layers"][0]["id"] == "satelite_maptiler" and "key=chave-de-teste" in m["url"] and "MapTiler" in m["attribution"]
    assert "https://api.maptiler.com" in c.get("/app/mapa.html").headers["content-security-policy"]


def test_sem_os_dois_consentimentos_nada_e_enviado():
    c = novo_cliente()
    assert pedir_codigo(c, dados=False).status_code == 422
    assert pedir_codigo(c, msgs=False).status_code == 422
    assert OUTBOX == [] and db.get_producer_by_phone(TEL_N) is None


def test_fluxo_completo_cria_conta_grava_consentimentos_e_abre_sessao():
    c = novo_cliente()
    r = pedir_codigo(c)
    assert r.status_code == 200 and r.json()["enviado"] and OUTBOX[-1]["to"] == TEL_N
    assert db.get_producer_by_phone(TEL_N) is None  # nada de conta antes de provar o número
    r = c.post("/api/signup/verify", json={"phone": TEL, "code": ultimo_codigo()})
    assert r.status_code == 200 and r.json()["estado"] == "AGUARDA_TALHAO"
    p = db.get_producer_by_phone(TEL_N)
    assert p.consent and p.source == "site" and p.name == "Maria" and p.state == "AGUARDA_TALHAO"
    cons = db.list_consents(TEL_N)
    assert {x["purpose"] for x in cons} == {"dados_localizacao", "mensagens"} and all(x["origin"] == "site" and x["text_version"] == "v0" for x in cons)
    assert c.get("/api/me").json()["state"] == "AGUARDA_TALHAO"


def test_codigo_nao_fica_em_texto_nem_no_banco_nem_no_registro_de_mensagens():
    c = novo_cliente()
    pedir_codigo(c)
    codigo = ultimo_codigo()
    with db.connect() as con:
        v = con.execute("SELECT code_hash FROM verifications").fetchone()["code_hash"]
        logs = " ".join(r["content"] for r in con.execute("SELECT content FROM messages").fetchall())
    assert codigo not in v and len(v) == 64 and v == auth.hash_code(TEL_N, codigo)
    assert codigo not in logs and "omitido" in logs


def test_codigo_errado_5_vezes_trava_ate_pedir_outro():
    c = novo_cliente()
    pedir_codigo(c)
    certo = ultimo_codigo()
    errado = "000000" if certo != "000000" else "111111"
    for _ in range(5):  # as 5 tentativas são aceitas (e erradas)
        assert c.post("/api/signup/verify", json={"phone": TEL, "code": errado}).status_code == 400
    assert c.post("/api/signup/verify", json={"phone": TEL, "code": errado}).status_code == 429
    assert c.post("/api/signup/verify", json={"phone": TEL, "code": certo}).status_code == 429  # nem o certo passa
    pedir_codigo(c)  # um código novo recomeça
    assert c.post("/api/signup/verify", json={"phone": TEL, "code": ultimo_codigo()}).status_code == 200


def test_codigo_vale_uma_vez_so():
    c = novo_cliente()
    pedir_codigo(c)
    cod = ultimo_codigo()
    assert c.post("/api/signup/verify", json={"phone": TEL, "code": cod}).status_code == 200
    assert novo_cliente().post("/api/signup/verify", json={"phone": TEL, "code": cod}).status_code == 400


def test_codigo_expira_em_10_minutos():
    c = novo_cliente()
    pedir_codigo(c)
    cod = ultimo_codigo()
    with db.connect() as con:
        con.execute("UPDATE verifications SET expires_at=?", ((datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),))
    assert c.post("/api/signup/verify", json={"phone": TEL, "code": cod}).status_code == 400


def test_codigo_novo_invalida_o_anterior():
    c = novo_cliente()
    pedir_codigo(c)
    velho = ultimo_codigo()
    pedir_codigo(c)
    novo = ultimo_codigo()
    if velho != novo:
        assert c.post("/api/signup/verify", json={"phone": TEL, "code": velho}).status_code == 400
    assert c.post("/api/signup/verify", json={"phone": TEL, "code": novo}).status_code == 200


def test_limite_de_60_segundos_entre_codigos(monkeypatch):
    monkeypatch.setattr(auth, "COOLDOWN_S", 60)
    c = novo_cliente()
    assert pedir_codigo(c).status_code == 200
    assert pedir_codigo(c).status_code == 429


def test_limite_de_3_codigos_por_hora_por_telefone():
    c = novo_cliente()
    assert [pedir_codigo(c).status_code for _ in range(3)] == [200, 200, 200]
    assert pedir_codigo(c).status_code == 429
    assert pedir_codigo(c, tel="65 99999-0002").status_code == 200  # outro número não é afetado


def test_limite_por_ip(monkeypatch):
    monkeypatch.setattr(auth, "PER_IP_HOUR", 3)
    c = novo_cliente()
    for i in range(3):
        assert pedir_codigo(c, tel=f"65 98888-000{i}").status_code == 200
    assert pedir_codigo(c, tel="65 98888-0009").status_code == 429


def test_telefone_invalido_e_numero_de_sucessor():
    c = novo_cliente()
    assert pedir_codigo(c, tel="123").status_code == 422
    dono = db.create_producer(Producer(phone="+5565999990100", consent=True, state="ATIVO"))
    db.add_contact(dono.id, "+5565999990200")  # o mesmo número que o site normaliza a partir de "65 99999-0200"
    OUTBOX.clear()
    r = pedir_codigo(c, tel="65 99999-0200")
    assert r.status_code == 200 and r.json()["enviado"] and OUTBOX == []  # resposta igual à de sucesso, nada enviado: não revela quem usa o BALK


def test_whatsapp_que_falha_cai_para_sms(monkeypatch):
    class Quebrado:
        name = "whatsapp"
        def send(self, *a, **k):
            raise RuntimeError("fora do ar")
    class Sms:
        enviados = []
        def send(self, phone, text, media_url=None, proactive=False, purpose=None):
            Sms.enviados.append(text)
    from app import delivery
    monkeypatch.setattr(delivery, "get_channel", lambda n: Quebrado() if n == "whatsapp" else Sms())
    r = pedir_codigo(novo_cliente())
    assert r.json()["enviado"] and r.json()["canal"] == "sms" and "verificação" in Sms.enviados[0]


# ---------------------------------------------------------------- sessão e proteção
def test_cookie_de_sessao_e_httponly_samesite_e_o_banco_guarda_so_o_hash():
    c = novo_cliente()
    pedir_codigo(c)
    r = c.post("/api/signup/verify", json={"phone": TEL, "code": ultimo_codigo()})
    setc = r.headers["set-cookie"].lower()
    assert "balk_session=" in setc and "httponly" in setc and "samesite=lax" in setc
    token = c.cookies.get("balk_session")
    with db.connect() as con:
        hashes = [x["token_hash"] for x in con.execute("SELECT token_hash FROM sessions").fetchall()]
    assert token not in hashes and len(hashes) == 1 and hashes[0] == db_site._hash(token)


def test_sem_sessao_tudo_da_conta_da_401():
    c = novo_cliente()
    for m, u in [("get", "/api/me"), ("get", "/api/plots"), ("get", "/api/history"), ("get", "/api/export"), ("post", "/api/finish")]:
        assert getattr(c, m)(u).status_code == 401, u


def test_sessao_revogada_deixa_de_valer():
    c = entrar()
    assert c.post("/api/logout").status_code == 200
    assert c.get("/api/me").status_code == 401


def test_csrf_origem_de_outro_site_e_recusada():
    c = entrar()
    g = {"name": "A", "geometry": quadrado(LAT, LON)}
    assert c.post("/api/plots", json=g, headers={"Origin": "https://malicioso.example"}).status_code == 403
    assert c.post("/api/plots", json=g, headers={"Origin": "http://testserver"}).status_code == 200


def test_cabecalhos_de_seguranca_nas_paginas_do_site():
    r = novo_cliente().get("/app/mapa.html")
    assert r.status_code == 200 and "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert novo_cliente().get("/api/config").headers["cache-control"] == "no-store"
    assert novo_cliente().get("/").status_code == 200


# ---------------------------------------------------------------- talhões
def test_talhao_valido_e_gravado_com_area_calculada():
    c = entrar()
    r = c.post("/api/plots", json={"name": "Baixada", "geometry": quadrado(LAT, LON, 300), "crop": "soja", "planting_date": "2026-10-20"})
    assert r.status_code == 200
    t = r.json()
    assert abs(t["area_ha"] - 9.0) < 0.3 and t["crop"] == "soja" and t["planting_date"] == "2026-10-20"
    assert [x["name"] for x in c.get("/api/plots").json()["talhoes"]] == ["Baixada"]


@pytest.mark.parametrize("corpo,trecho", [
    ({"name": "x", "geometry": {"type": "Polygon", "coordinates": [[[-46.66, -23.58], [-46.65, -23.59], [-46.65, -23.58], [-46.66, -23.59], [-46.66, -23.58]]]}}, "inválido"),
    ({"name": "x", "geometry": quadrado(lado_m=15)}, "abaixo do mínimo"),
    ({"name": "x", "geometry": quadrado(40.4, -3.7)}, "fora do Brasil"),
    ({"name": "", "geometry": quadrado()}, "nome"),
    ({"name": "x", "geometry": quadrado(), "crop": "bananada"}, "cultura"),
    ({"name": "x", "geometry": quadrado(), "planting_date": "2999-01-01"}, "data de plantio"),
])
def test_servidor_recusa_talhao_invalido_mesmo_que_o_navegador_deixe_passar(corpo, trecho):
    r = entrar().post("/api/plots", json=corpo)
    assert r.status_code == 422 and trecho in " ".join(r.json()["detail"]["erros"])


def test_sobreposicao_e_recusada_mas_editar_o_proprio_talhao_nao_conflita():
    c = entrar()
    a = c.post("/api/plots", json={"name": "A", "geometry": quadrado(LAT, LON, 300)}).json()
    assert c.post("/api/plots", json={"name": "B", "geometry": quadrado(LAT, LON, 300, dx_m=100)}).status_code == 422
    r = c.put(f"/api/plots/{a['id']}", json={"name": "A2", "geometry": quadrado(LAT, LON, 320), "crop": "milho"})
    assert r.status_code == 200 and r.json()["name"] == "A2" and r.json()["crop"] == "milho"


def test_um_produtor_nao_enxerga_nem_altera_talhao_de_outro():
    a, b = entrar(TEL, "A"), entrar("65 99999-0003", "B")
    pid = a.post("/api/plots", json={"name": "Meu", "geometry": quadrado(LAT, LON)}).json()["id"]
    assert b.get("/api/plots").json()["talhoes"] == []
    assert b.put(f"/api/plots/{pid}", json={"name": "Roubado", "geometry": quadrado(LAT, LON)}).status_code == 404
    assert b.delete(f"/api/plots/{pid}").status_code == 404
    assert a.get("/api/plots").json()["talhoes"][0]["name"] == "Meu"


def test_excluir_talhao():
    c = entrar()
    pid = c.post("/api/plots", json={"name": "A", "geometry": quadrado(LAT, LON)}).json()["id"]
    assert c.delete(f"/api/plots/{pid}").status_code == 200 and c.get("/api/plots").json()["talhoes"] == []


def test_busca_de_lugar_exige_sessao_e_tem_reserva_offline():
    assert novo_cliente().get("/api/geocode?q=sorriso").status_code == 401
    r = entrar().get("/api/geocode?q=sorriso").json()["resultados"]
    assert r and abs(r[0]["lat"] - (-12.54)) < 0.1


# ---------------------------------------------------------------- concluir cadastro, vários talhões, relatório por talhão
def test_concluir_sem_talhao_e_recusado():
    assert entrar().post("/api/finish", json={}).status_code == 422


def test_concluir_ativa_fixa_o_ponto_no_maior_talhao_e_manda_um_relatorio_por_talhao():
    c = entrar()
    c.post("/api/plots", json={"name": "Pequeno", "geometry": quadrado(LAT, LON, 150), "crop": "milho", "planting_date": "2026-10-25"})
    c.post("/api/plots", json={"name": "Grande", "geometry": quadrado(LAT, LON + 0.05, 400), "crop": "soja", "planting_date": "2026-10-20"})
    OUTBOX.clear()
    r = c.post("/api/finish", json={})
    assert r.status_code == 200 and r.json()["talhoes"] == 2
    p = db.get_producer_by_phone(TEL_N)
    assert p.state == "ATIVO" and abs(p.lon - (LON + 0.05 + 0.002)) < 0.01  # centro do MAIOR talhão
    textos = [m["text"] for m in OUTBOX if "/100" in m["text"]]
    assert len(textos) == 2 and any("Grande" in t for t in textos) and any("Pequeno" in t for t in textos)
    assert all("/r/" in t for t in textos)  # cada um com o link do seu relatório
    assert len({re.search(r"/r/(\S+)", t).group(1) for t in textos}) == 2


def test_um_talhao_so_nao_leva_o_nome_na_mensagem():
    c = entrar()
    c.post("/api/plots", json={"name": "Unico", "geometry": quadrado(LAT, LON, 300), "crop": "soja"})
    OUTBOX.clear()
    c.post("/api/finish", json={})
    assert not any("Unico" in m["text"] for m in OUTBOX)


def _produtor_com_talhoes(n=2, crop="soja", plantio="2026-10-20"):
    p = db.create_producer(Producer(phone="+5565999990500", consent=True, state="ATIVO", lat=LAT, lon=LON, source="site"))
    for i in range(n):
        g = quadrado(LAT, LON + i * 0.004, 250)
        db.create_plot(p.id, f"T{i + 1}", g, 6.0, crop, plantio)
    return db.get_producer(p.id)


def test_analise_gera_um_relatorio_por_talhao_com_clima_compartilhado_sem_repetir_pulverizacao(monkeypatch):
    p = _produtor_com_talhoes(2)
    res = analyze_producer(p.id, full=True, now=NOW)
    reps = [m for m in res["messages"] if m["kind"] == "report"]
    assert len(reps) == 2 and {m["plot_name"] for m in reps} == {"T1", "T2"} and len(res["units"]) == 2
    assert len({m["report_token"] for m in reps}) == 2
    assert sum(1 for m in res["messages"] if m["type"] == "pulverizacao") <= 1  # mesmo clima: um aviso só


def test_silencio_vale_por_talhao_e_a_geada_de_um_nao_cala_o_outro(monkeypatch):
    p = _produtor_com_talhoes(2)
    monkeypatch.setattr("app.service.get_weather", lambda lat, lon, now: Weather(hours=simulated.scenario_weather("geada", NOW)))
    enviados = run_daily(NOW)
    geadas = [e for e in enviados if e["type"] == "geada" and e["ok"]]
    assert {e["plot_id"] for e in geadas} == {x["id"] for x in db.list_plots(p.id)}  # um aviso de geada para cada talhão
    assert any("T1" in e["text"] for e in geadas) and any("T2" in e["text"] for e in geadas)
    # uma hora depois: os dois talhões estão em silêncio de 72 h para geada
    assert [e for e in run_daily(NOW + timedelta(hours=1)) if e["type"] == "geada"] == []
    # talhão novo: não tem silêncio ainda, recebe o seu aviso
    db.create_plot(p.id, "T3", quadrado(LAT, LON + 0.02, 250), 6.0, "soja", "2026-10-20")
    novos = [e for e in run_daily(NOW + timedelta(hours=2)) if e["type"] == "geada"]
    assert len(novos) == 1 and "T3" in novos[0]["text"]


def test_cota_semanal_conta_todos_os_talhoes(monkeypatch):
    p = _produtor_com_talhoes(3)
    monkeypatch.setattr("app.service.get_weather", lambda lat, lon, now: Weather(hours=simulated.scenario_weather("bom", NOW)))
    ev = run_daily(NOW)
    nao_urgentes = [e for e in ev if e["type"] != "geada" and e["ok"]]
    assert len(nao_urgentes) <= 2  # máximo por dia/semana por contato, somando os talhões


# ---------------------------------------------------------------- safras e observações
def test_safra_abre_com_cultura_e_plantio_e_observacao_e_idempotente():
    p = _produtor_com_talhoes(1)
    analyze_producer(p.id, full=False, now=NOW)
    analyze_producer(p.id, full=False, now=NOW)
    seasons = db_site.seasons_overview(p.id)
    assert len(seasons) == 1 and seasons[0]["crop"] == "soja" and seasons[0]["start_date"] == "2026-10-20"
    assert seasons[0]["n_observacoes"] == 1  # a mesma cena não vira dois registros


def test_trocar_a_cultura_fecha_a_safra_e_abre_outra():
    p = _produtor_com_talhoes(1)
    analyze_producer(p.id, full=False, now=NOW)
    plot = db.list_plots(p.id)[0]
    db.update_plot(plot["id"], p.id, crop="milho", planting_date="2026-11-05")
    analyze_producer(p.id, full=False, now=NOW)
    ss = db_site.seasons_overview(p.id)
    assert {s["crop"] for s in ss} == {"soja", "milho"} and len(db_site.open_seasons(p.id)) == 1


def test_historico_de_safras_anteriores_alimenta_o_alerta_de_estresse():
    p = _produtor_com_talhoes(1)
    plot = db.list_plots(p.id)[0]
    with db.connect() as con:  # safra anterior do MESMO talhão e cultura, com vigor alto na mesma fase do ciclo
        sid = con.execute("INSERT INTO seasons (producer_id, plot_id, crop, start_date, end_date, yield_t_ha, created_at) VALUES (?,?,?,?,?,?,?)",
                          (p.id, plot["id"], "soja", "2025-10-20", "2026-03-01", 3.8, "2026-03-01")).lastrowid
        for d in ("2025-11-24", "2025-11-26", "2025-11-28", "2025-11-30"):
            con.execute("INSERT INTO observations (producer_id, plot_id, season_id, scene_date, source, ndvi_mean, area_ha) VALUES (?,?,?,?,?,?,?)",
                        (p.id, plot["id"], sid, d, "simulado", 0.97, 6.0))
    res = analyze_producer(p.id, full=False, now=NOW)
    estresse = [a for a in res["alerts"] if a["type"] == "estresse"]
    assert estresse and estresse[0]["evidence"]["referencia"] == "historico" and estresse[0]["confidence"] == "media"


# ---------------------------------------------------------------- conversa pelo WhatsApp
def test_quem_verificou_no_site_e_ainda_nao_desenhou_recebe_o_link_do_mapa():
    entrar()
    r = handle_message(TEL_N, "oi")
    assert "/m/" in r.text and "desenhe" in r.text.lower()


def test_comando_mapa_gera_link_de_uso_unico_que_so_abre_uma_vez():
    p = _produtor_com_talhoes(1)
    r = handle_message(p.phone, "MAPA")
    token = re.search(r"/m/([\w-]+)", r.text).group(1)
    c = novo_cliente()
    assert c.get(f"/m/{token}").status_code == 200  # a página intermediária NÃO gasta o link (robô de pré-visualização)
    assert c.get("/api/me").status_code == 401
    r1 = c.post(f"/m/{token}", follow_redirects=False)
    assert r1.status_code == 303 and r1.headers["location"] == "/app/mapa.html" and "httponly" in r1.headers["set-cookie"].lower()
    assert c.get("/api/me").json()["id"] == p.id
    assert novo_cliente().post(f"/m/{token}", follow_redirects=False).status_code == 404  # segunda vez: gasto


def test_link_do_mapa_expira_em_30_minutos():
    p = _produtor_com_talhoes(1)
    token = db_site.create_magic_link(p.id)
    with db.connect() as con:
        con.execute("UPDATE magic_links SET expires_at=?", ((datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),))
    assert novo_cliente().post(f"/m/{token}", follow_redirects=False).status_code == 404
    assert novo_cliente().post("/m/lixo-lixo-lixo-lixo-lixo", follow_redirects=False).status_code == 404


def test_sucessor_nao_recebe_link_do_mapa():
    p = _produtor_com_talhoes(1)
    db.add_contact(p.id, "+5565999990999")
    db.set_contact_state("+5565999990999", "ATIVO")
    assert "/m/" not in handle_message("+5565999990999", "MAPA").text


def test_comando_produtividade_fecha_a_safra():
    p = _produtor_com_talhoes(1)
    analyze_producer(p.id, full=False, now=NOW)
    r = handle_message(p.phone, "PRODUTIVIDADE 3,4")
    assert "3,4 t/ha" in r.text
    s = db_site.seasons_overview(p.id)[0]
    assert s["yield_t_ha"] == 3.4 and s["end_date"]


def test_produtividade_com_varios_talhoes_pergunta_qual_e_aceita_o_nome():
    p = _produtor_com_talhoes(2)
    analyze_producer(p.id, full=False, now=NOW)
    assert "Qual talhão" in handle_message(p.phone, "PRODUTIVIDADE 3,4").text
    assert "T2" in handle_message(p.phone, "PRODUTIVIDADE 4,1 T2").text
    por_nome = {s["plot_name"]: s for s in db_site.seasons_overview(p.id)}
    assert por_nome["T2"]["yield_t_ha"] == 4.1 and por_nome["T1"]["yield_t_ha"] is None


def test_produtividade_absurda_ou_sem_numero_e_recusada():
    p = _produtor_com_talhoes(1)
    analyze_producer(p.id, full=False, now=NOW)
    assert "Não entendi" in handle_message(p.phone, "PRODUTIVIDADE 900").text
    assert "Não entendi" in handle_message(p.phone, "PRODUTIVIDADE muita").text


def test_fechar_safra_pelo_site_so_da_propria_conta():
    c = entrar()
    c.post("/api/plots", json={"name": "A", "geometry": quadrado(LAT, LON), "crop": "soja", "planting_date": "2026-10-20"})
    c.post("/api/finish", json={})
    sid = c.get("/api/history").json()["safras"][0]["id"]
    outro = entrar("65 99999-0007", "Outro")
    assert outro.post(f"/api/seasons/{sid}/close", json={"yield_t_ha": 3}).status_code == 404
    assert c.post(f"/api/seasons/{sid}/close", json={"yield_t_ha": 0}).status_code == 422
    assert c.post(f"/api/seasons/{sid}/close", json={"yield_t_ha": 3.2}).status_code == 200
    assert c.get("/api/history").json()["safras"][0]["yield_t_ha"] == 3.2


# ---------------------------------------------------------------- conta: contato, saída, exportação, exclusão
def test_convite_de_segundo_contato_so_vale_depois_do_sim():
    c = entrar()
    OUTBOX.clear()
    assert c.post("/api/contacts", json={"phone": "65 99999-0555"}).status_code == 200
    assert OUTBOX and OUTBOX[-1]["to"] == "+5565999990555" and "SIM" in OUTBOX[-1]["text"]
    assert c.post("/api/contacts", json={"phone": "12"}).status_code == 422
    assert db.list_contacts(db.get_producer_by_phone(TEL_N).id, only_active=True) == []
    assert c.delete("/api/contacts/65 99999-0555".replace(" ", "%20")).status_code == 200


def test_exportar_traz_tudo_e_apagar_exige_confirmacao_e_remove_tudo():
    c = entrar()
    c.post("/api/plots", json={"name": "A", "geometry": quadrado(LAT, LON), "crop": "soja", "planting_date": "2026-10-20"})
    dados = c.get("/api/export").json()
    assert dados["produtor"]["phone"] == TEL_N and len(dados["talhoes"]) == 1 and len(dados["consentimentos"]) == 2
    assert c.request("DELETE", "/api/me", json={"confirmar": False}).status_code == 422
    assert c.request("DELETE", "/api/me", json={"confirmar": True}).status_code == 200
    assert db.get_producer_by_phone(TEL_N) is None and db.list_consents(TEL_N) == []
    assert c.get("/api/me").status_code == 401  # a sessão também foi apagada


def test_parar_de_receber_revoga_consentimento_e_sessoes():
    c = entrar()
    assert c.post("/api/optout").status_code == 200
    p = db.get_producer_by_phone(TEL_N)
    assert p.state == "SAIU" and not p.consent and not db.has_consent(TEL_N, "mensagens")
    assert c.get("/api/me").status_code == 401


def test_voltar_depois_de_sair_reabre_a_conta_com_novo_aceite():
    c = entrar()
    c.post("/api/optout")
    c2 = entrar()
    p = db.get_producer_by_phone(TEL_N)
    assert p.consent and p.state == "AGUARDA_TALHAO" and db.has_consent(TEL_N, "mensagens") and c2.get("/api/me").status_code == 200


# ---------------------------------------------------------------- endurecimento (achados da auditoria de segurança)
def test_x_forwarded_for_forjado_nao_burla_os_limites_por_ip(monkeypatch):
    monkeypatch.setattr(auth, "PER_IP_HOUR", 2)
    c = novo_cliente()
    ok = [c.post("/api/signup/start", headers={"X-Forwarded-For": f"10.0.0.{i}"},
                 json={"name": "", "phone": f"65 97777-000{i}", "consent_dados": True, "consent_mensagens": True}).status_code for i in range(3)]
    assert ok == [200, 200, 429]  # trocar o cabeçalho a cada pedido não ajuda


def test_tentativas_do_codigo_sao_contadas_de_forma_atomica():
    c = novo_cliente()
    pedir_codigo(c)
    v = db.connect().execute("SELECT id FROM verifications").fetchone()["id"]
    assert [db_site.take_attempt(v, 5) for _ in range(8)] == [True] * 5 + [False] * 3


def test_pagina_do_link_do_mapa_nao_reflete_a_url_e_o_post_exige_mesma_origem():
    c = novo_cliente()
    assert c.get("/m/x%22%3E%3Cmeta%20http-equiv=refresh%20content=%220;url=https://evil.example%22%3E").status_code == 404
    p = _produtor_com_talhoes(1)
    token = db_site.create_magic_link(p.id)
    pagina = c.get(f"/m/{token}")
    assert pagina.status_code == 200 and token not in pagina.text  # o token não vai para o HTML
    assert c.post(f"/m/{token}", headers={"Origin": "https://malicioso.example"}, follow_redirects=False).status_code == 403
    assert c.post(f"/m/{token}", headers={"Origin": "http://testserver"}, follow_redirects=False).status_code == 303  # o 403 não gastou o link


def test_convites_limitados_por_dia_e_sem_revelar_quem_ja_usa_o_balk():
    c = entrar()
    dono_de_outro = db.create_producer(Producer(phone="+5565999991111", consent=True, state="ATIVO"))
    OUTBOX.clear()
    r = c.post("/api/contacts", json={"phone": "5565999991111"})
    assert r.status_code == 200 and "Enviei o convite" in r.json()["mensagem"] and OUTBOX == []  # igual ao sucesso, nada enviado
    assert [c.post("/api/contacts", json={"phone": f"5565999992{i:03d}"}).status_code for i in range(4)] == [200, 200, 200, 429]
    assert db.list_contacts(dono_de_outro.id) == []


def test_relatorio_pelo_site_tem_limite_diario():
    c = entrar()
    c.post("/api/plots", json={"name": "A", "geometry": quadrado(LAT, LON)})
    codigos = [c.post("/api/finish", json={"enviar_relatorio": True}).status_code for _ in range(4)]
    assert codigos == [200, 200, 200, 429]


def test_geometria_gravada_e_a_validada_sem_chaves_extras_e_com_limite_de_vertices():
    c = entrar()
    g = quadrado(LAT, LON, 300)
    g["coordinates"][0] = [[str(x), str(y)] for x, y in g["coordinates"][0]]  # coordenadas em texto
    g["propriedade_extra"] = "x" * 1000
    r = c.post("/api/plots", json={"name": "A", "geometry": g})
    assert r.status_code == 200
    gravado = c.get("/api/plots").json()["talhoes"][0]["geometry"]
    assert set(gravado) == {"type", "coordinates"} and all(isinstance(v, float) for p in gravado["coordinates"][0] for v in p)
    import math
    ring = [[LON + 0.01 * math.cos(t / 600 * 6.2832), LAT + 0.01 * math.sin(t / 600 * 6.2832)] for t in range(600)]
    ring.append(ring[0])
    r = c.post("/api/plots", json={"name": "B", "geometry": {"type": "Polygon", "coordinates": [ring]}})
    assert r.status_code == 422 and "vértices demais" in " ".join(r.json()["detail"]["erros"])


def test_exportacao_nao_traz_tokens_de_relatorio_e_a_limpeza_apaga_o_vencido():
    c = entrar()
    c.post("/api/plots", json={"name": "A", "geometry": quadrado(LAT, LON), "crop": "soja", "planting_date": "2026-10-20"})
    c.post("/api/finish", json={})
    dados = c.get("/api/export").json()
    assert dados["mensagens_enviadas"] and all("report_token" not in m for m in dados["mensagens_enviadas"])
    with db.connect() as con:
        con.execute("UPDATE verifications SET created_at='2020-01-01T00:00:00'")
        con.execute("UPDATE sessions SET expires_at='2020-01-01T00:00:00'")
    r = db_site.purge_expired()
    assert r["verificacoes"] >= 1 and r["sessoes"] >= 1
    assert c.get("/api/me").status_code == 401


def test_balk_env_invalido_nao_liga_a_demo_em_silencio(monkeypatch):
    from app import config
    monkeypatch.setenv("BALK_ENV", "prod")
    with pytest.raises(RuntimeError, match="BALK_ENV inválido"):
        config.env()


def test_demo_tambem_exige_a_chave_quando_ela_existe(monkeypatch):
    monkeypatch.setenv("BALK_API_KEY", "k" * 32)
    c = novo_cliente()
    assert c.get("/outbox").status_code == 401 and c.post("/simulate/reset").status_code == 401
    assert c.get("/outbox", headers={"X-API-Key": "k" * 32}).status_code == 200


def test_cabecalhos_de_endurecimento(monkeypatch):
    c = novo_cliente()
    r = c.get("/app/mapa.html", headers={"X-Request-ID": "<script>"})
    assert r.headers["referrer-policy"] == "strict-origin" and r.headers["x-request-id"] != "<script>"
    assert c.get("/health").headers["referrer-policy"] == "no-referrer"
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://balk.exemplo.com.br")
    assert "max-age" in c.get("/health").headers["strict-transport-security"]


def test_producao_exige_segredo_de_autenticacao(monkeypatch):
    from app import config
    monkeypatch.setenv("BALK_ENV", "production")
    monkeypatch.delenv("BALK_AUTH_SECRET", raising=False)
    assert any("BALK_AUTH_SECRET" in x for x in config.production_problems())
    monkeypatch.setenv("BALK_AUTH_SECRET", "s" * 32)
    assert not any("BALK_AUTH_SECRET" in x for x in config.production_problems())


def test_codigo_usa_template_proprio_do_whatsapp(monkeypatch):
    from app.channels import WhatsAppChannel
    visto = {}
    monkeypatch.setenv("WHATSAPP_TEMPLATE_NAME", "geral")
    monkeypatch.setenv("WHATSAPP_CODE_TEMPLATE_NAME", "codigo_verificacao")
    monkeypatch.setattr(WhatsAppChannel, "_post", lambda self, payload: visto.update(payload) or "id1")
    WhatsAppChannel().send("+5565999990001", "BALK: código 123456", proactive=True, purpose="code")
    assert visto["template"]["name"] == "codigo_verificacao"
    visto.clear()
    WhatsAppChannel().send("+5565999990001", "alerta", proactive=True)
    assert visto["template"]["name"] == "geral"


def test_numero_digitado_no_site_ganha_o_55_e_casa_com_o_do_whatsapp():
    assert auth.site_phone("65 99999-0001") == "+5565999990001" == auth.site_phone("(65) 9999-90001")
    assert auth.site_phone("55 65 99999-0001") == "+5565999990001"  # já com o código do país
    assert auth.site_phone("6533330001") == "+556533330001"  # fixo com DDD (10 dígitos)
    c = entrar()
    assert handle_message("5565999990001", "oi").producer_id == db.get_producer_by_phone(TEL_N).id  # o WhatsApp manda sem "+"
