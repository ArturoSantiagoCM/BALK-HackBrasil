"""Backtest: contas e classificação com séries sintéticas (sem rede)."""
from datetime import datetime, timedelta

from app import backtest


def _rows(dias, fc_min, tr_min, fc_rain=0.0, tr_rain=0.0, start="2025-06-01"):
    """Cada dia: 24 horas, madrugada (0-9h) em fc_min/tr_min, resto 15 °C; chuva do dia concentrada na hora 12."""
    rows = []
    d0 = datetime.fromisoformat(start)
    for d in range(dias):
        mins_f, mins_t, rf, rt = fc_min[d], tr_min[d], fc_rain[d] if isinstance(fc_rain, list) else fc_rain, tr_rain[d] if isinstance(tr_rain, list) else tr_rain
        for h in range(24):
            t = (d0 + timedelta(days=d, hours=h)).strftime("%Y-%m-%dT%H:00")
            rows.append({"time": t, "fc_t": mins_f if h < 10 else 15.0, "tr_t": mins_t if h < 10 else 15.0,
                         "fc_p": rf if h == 12 else 0.0, "tr_p": rt if h == 12 else 0.0})
    return rows


def test_matriz_de_confusao_conta_acerto_alarme_falso_e_perda():
    # dia 0: ambos geam (acerto); 1: só a previsão (alarme falso); 2: só o real (perda); 3: nenhum
    rows = _rows(4, [2.0, 2.5, 5.0, 8.0], [1.5, 6.0, 2.0, 9.0])
    r = backtest.evaluate_point({"rows": rows}, frost_limit=3.0)
    g = r["geada"]
    assert (g["acertos"], g["alarmes_falsos"], g["perdas"], g["sem_evento"]) == (1, 1, 1, 1)
    assert g["precisao"] == 0.5 and g["recall"] == 0.5 and g["f1"] == 0.5 and r["noites"] == 4


def test_margem_troca_alarme_falso_por_menos_perdas():
    rows = _rows(2, [4.0, 8.0], [2.0, 9.0])  # previsão 4 °C numa noite que geou a 2 °C
    r = backtest.evaluate_point({"rows": rows}, frost_limit=3.0)
    assert r["geada_margem"][0.0]["perdas"] == 1 and r["geada_margem"][1.0]["perdas"] == 0 and r["geada_margem"][1.0]["acertos"] == 1


def test_erro_medio_e_vies_da_temperatura():
    rows = _rows(2, [5.0, 3.0], [3.0, 2.0])  # +2 e +1 de erro
    t = backtest.evaluate_point({"rows": rows}, 3.0)["temperatura"]
    assert t["mae"] == 1.5 and t["vies"] == 1.5


def test_noite_com_poucas_horas_validas_e_descartada():
    rows = _rows(1, [2.0], [2.0])
    for r in rows[:5]:
        r["fc_t"] = None  # só 5 horas válidas na madrugada: não vale
    assert backtest.evaluate_point({"rows": rows}, 3.0)["noites"] == 0


def test_chuva_forte_do_dia():
    rows = _rows(3, [10.0] * 3, [10.0] * 3, fc_rain=[8.0, 8.0, 0.0], tr_rain=[9.0, 0.0, 6.0])
    c = backtest.evaluate_point({"rows": rows}, 3.0)["chuva"]
    assert (c["acertos"], c["alarmes_falsos"], c["perdas"]) == (1, 1, 1)


def test_run_backtest_soma_pontos_e_gera_markdown_sem_rede():
    def falso(lat, lon, start, end):
        return {"rows": _rows(4, [2.0, 2.5, 5.0, 8.0], [1.5, 6.0, 2.0, 9.0])}
    res = backtest.run_backtest(points=[("A", -28, -52), ("B", -27, -50)], periods=[("2025-06-01", "2025-06-04")], fetch=falso)
    assert res["total"]["geada"]["acertos"] == 2 and res["total"]["noites"] == 8 and len(res["pontos"]) == 2
    md = backtest.to_markdown(res)
    assert "Backtest" in md and "estação do INMET" in md and "| A |" in md and "Quanto de margem" in md
