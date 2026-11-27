"""Página HTML do relatório detalhado (uma só, leve, boa para celular). Sem JavaScript, sem recursos externos."""
import base64
from datetime import datetime
from html import escape as esc
from pathlib import Path
from typing import Optional

CSS = """
:root{--v:#0b6e4f;--v2:#075e54;--c:#667;--b:#dfe5e1}
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,Segoe UI,Roboto,sans-serif;background:#f4f6f4;color:#1c1c1c}
header{background:var(--v2);color:#fff;padding:16px 18px}header h1{margin:0;font-size:21px}header p{margin:4px 0 0;opacity:.9;font-size:14px}
main{max-width:1100px;margin:auto;padding:12px}.indice{background:#fff;border-radius:12px;padding:10px 14px;font-size:14px;line-height:1.9;box-shadow:0 1px 4px #0002}
code{font-size:12px;background:#f1f4f2;padding:1px 4px;border-radius:4px}section{background:#fff;border-radius:14px;box-shadow:0 1px 4px #0002;padding:16px;margin:12px 0}
h2{margin:0 0 8px;font-size:18px;color:var(--v2)}h3{margin:14px 0 6px;font-size:15px}p{margin:6px 0}
.aviso{background:#fff3e0;border-left:5px solid #ef6c00;padding:10px 12px;border-radius:8px;font-size:15px;margin:10px 0}
.sim{background:#ffebee;border-left-color:#c62828;font-weight:600}
.msg{background:#dcf8c6;border-radius:10px;padding:10px 12px;white-space:pre-wrap;margin:8px 0;font-size:15px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:6px 7px;border-bottom:1px solid var(--b);text-align:left;vertical-align:top}
th{background:#eef3f0;font-weight:600}.tw{overflow-x:auto}
.chip{display:inline-block;border-radius:10px;padding:0 8px;font-size:12px;color:#fff;white-space:nowrap}
.confirmado{background:#2e7d32}.ajustado{background:#1565c0}.parcial{background:#f9a825;color:#222}.premissa{background:#757575}
.ok{color:#2e7d32;font-weight:700}.nok{color:#c62828;font-weight:700}
figure{margin:14px 0}figure img{width:100%;height:auto;border:1px solid var(--b);border-radius:8px}
figcaption{font-size:14px;color:#333}figcaption b{color:var(--v2)}.como{color:var(--c)}
.bar{background:#e0e0e0;border-radius:6px;height:10px;min-width:70px}.bar i{display:block;height:10px;border-radius:6px;background:#2e7d32}
details{margin:8px 0}summary{cursor:pointer;font-weight:600}
.card{border:1px solid var(--b);border-radius:10px;padding:10px 12px;margin:10px 0;background:#fafcfb}
ul{margin:6px 0;padding-left:20px}footer{font-size:13px;color:var(--c);padding:6px 14px 30px;max-width:920px;margin:auto}
a{color:#0b6e4f}.small{font-size:13px;color:var(--c)}
@media print{header{background:#fff;color:#000}section{box-shadow:none;break-inside:avoid}}
"""


def _fmt_dt(s: str) -> str:
    try:
        return datetime.fromisoformat(s).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return s or ""


def _chip(status: str, txt: str) -> str:
    return f'<span class="chip {esc(status)}">{esc(txt)}</span>'


def _link(url: str, title: str) -> str:
    return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(title or url)}</a>' if url else esc(title or "")


def _img_src(name: str, img_dir: Optional[Path], base_url: str, inline: bool) -> str:
    if inline and img_dir is not None and (img_dir / name).exists():
        return "data:image/png;base64," + base64.b64encode((img_dir / name).read_bytes()).decode()
    return f"{base_url}/{name}"


def _figure(im: dict, img_dir, base_url, inline) -> str:
    return (f'<figure id="img-{esc(im["arquivo"][:-4])}"><img src="{_img_src(im["arquivo"], img_dir, base_url, inline)}" '
            f'alt="{esc(im["titulo"])}" loading="lazy">'
            f'<figcaption><b>{esc(im["titulo"])}.</b> <span class="como">{esc(im["como_ler"])}</span><br>'
            f'<b>O que concluímos:</b> {esc(im["conclusao"])}</figcaption></figure>')


def _crop_block(c: dict) -> str:
    rows = []
    for r in c["fatores"]:
        faixa = r["faixa"]
        ideal = f'{faixa["b"]:g} a {faixa["c"]:g}'
        tol = f'{faixa["a"]:g} a {faixa["d"]:g}'
        if r["valor"] is None:
            val, nota = "sem dado (saiu da conta)", ""
        else:
            val = f'{r["valor"]:g} {esc(r["unidade"])}'
            nota = (f'<div class="bar"><i style="width:{int(r["nota"] * 100)}%"></i></div>{r["nota"]:.2f}')
        src = _link(r["fonte_url"], r["fonte_titulo"]) if r["fonte_url"] else esc(r["fonte_titulo"])
        rows.append(f'<tr><td>{esc(r["nome"])}</td><td>{val}</td><td>{esc(ideal)}</td><td>{esc(tol)}</td><td>{nota}</td>'
                    f'<td>{r["peso"]:g}</td><td>{_chip(r["status"], r["status_txt"])}<br><span class="small">{src}</span></td></tr>')
    from app.message.templates import CROPS
    teto = "<p class=\"small\">Algum fator zerou, então a nota máxima desta cultura é 40.</p>" if c["teto_40"] else ""
    tag = " (a sua cultura)" if c["informada"] else ""
    return (f'<div class="card"><h3>{esc(CROPS["pt"].get(c["crop"], c["crop"]).capitalize())}{tag}: nota {c["nota"]}/100, confiança {esc(c["confianca"])}</h3>'
            f'<p><b>Fator que mais limita:</b> {esc(c["limitante_nome"])}. {esc(c["orientacao"])}</p>'
            f'<div class="tw"><table><tr><th>Fator</th><th>Sua área</th><th>Ideal</th><th>Tolerado</th><th>Nota (0-1)</th><th>Peso</th>'
            f'<th>Fonte da faixa</th></tr>{"".join(rows)}</table></div>{teto}'
            f'<p class="small">Conta: nota = 100 × soma(peso × nota do fator) ÷ soma dos pesos. Fator sem dado sai da conta e a confiança cai.</p></div>')


def _alert_block(a: dict) -> str:
    tipo = {"pulverizacao": "Pulverização", "geada": "Geada", "estresse": "Estresse da lavoura", "colheita": "Colheita"}[a["tipo"]]
    rows = "".join(f'<tr><td>{esc(str(r["criterio"]))}</td><td>{esc(str(r["limite"]))}</td><td>{esc(str(r["observado"]))}</td>'
                   f'<td class="{"ok" if r["atende"] else "nok"}">{"atende" if r["atende"] else "não atende"}</td></tr>'
                   for r in a["criterios"])
    fontes = " ".join(_link(u, u.split("//")[-1][:48]) for u in a["regra_fontes"])
    return (f'<div class="card"><h3>{tipo}: {esc(a["acao"])}</h3>'
            f'<p>Janela: <b>{esc(a["janela"] or "sem janela definida")}</b> · confiança <b>{esc(a["confianca"])}</b></p>'
            f'<p><b>Por quê:</b> {esc(a["por_que"])}</p>'
            f'<div class="tw"><table><tr><th>Critério</th><th>Limite da regra</th><th>Valor previsto</th><th>Resultado</th></tr>{rows}</table></div>'
            f'<p>{_chip(a["regra_status"], a["regra_status_txt"])} <span class="small">{esc(a["regra_resumo"])}</span></p>'
            f'<p class="small">{fontes}</p></div>')


def _relations_block(r: dict) -> str:
    if not r:
        return ""
    items = []
    if r.get("relevo"):
        items.append(f'<li><b>Relevo:</b> {esc(r["relevo"])}' + (f', encosta voltada para {esc(r["aspecto"])}' if r.get("aspecto") else "")
                     + ". Classes da Embrapa: plano até 3%, suave ondulado 3-8%, ondulado 8-20%, forte ondulado 20-45%.</li>")
    e = r.get("erosao") or {}
    if e.get("indice") is not None:
        items.append(f'<li><b>Erosão:</b> índice {e["indice"]:.2f} (risco {esc(e["classe"])}). Declividade x (chuva, cobertura, solo). '
                     'Índice relativo, <u>não</u> é perda de solo. <i>Hipótese em validação.</i></li>')
    u = r.get("umidade") or {}
    if u.get("ndmi") is not None:
        s = f'<li><b>Umidade da vegetação:</b> NDMI {u["ndmi"]:.2f} ({esc(u["classe"] or "-")})'
        if u.get("saldo_mm") is not None:
            s += f'; chuva menos evaporação prevista em 72 h: {u["saldo_mm"]:g} mm' + (". <b>Vale ficar de olho na água.</b>" if u.get("atencao") else ".")
        items.append(s + " <i>Cortes de classe: premissa da equipe.</i></li>")
    if r.get("geada_relevo_c") is not None and r["geada_relevo_c"] <= -0.3:
        items.append(f'<li><b>Baixada e geada:</b> o ponto mais baixo pode ficar até {abs(r["geada_relevo_c"]):.1f} °C mais frio que a previsão do ponto '
                     "(o ar frio escorre e se acumula nas baixadas; a magnitude é hipótese em validação).</li>")
    if r.get("area_fraca_pct") is not None:
        d = r.get("area_fraca_dir")
        items.append(f'<li><b>Área fraca:</b> {r["area_fraca_pct"]:.0f}% da área está mais de 1 desvio abaixo da referência da cena'
                     + (f", concentrada no lado {esc(d)}" if d and d != "C" else "") + ".</li>")
    zonas = ""
    if r.get("zonas"):
        trs = "".join(f'<tr><td>{z["id"]}</td><td>{esc(z["label"])}</td><td>{z["share_pct"]:.0f}%</td><td>{z["area_ha"]:.1f} ha</td>'
                      f'<td>{z["ndvi_mean"]:.2f}</td><td>{z.get("slope_mean", 0):.1f}%</td><td>{z.get("ndmi_mean", 0):.2f}</td></tr>'
                      for z in r["zonas"])
        zonas = ('<h3>Zonas de manejo</h3><div class="tw"><table><tr><th>Zona</th><th>Tipo</th><th>Parte da área</th><th>Área</th><th>NDVI</th>'
                 f'<th>Declive</th><th>NDMI</th></tr>{trs}</table></div>')
    return f'<ul>{"".join(items)}</ul>{zonas}'


STAT_LABELS = [  # (campo, rótulo, unidade, casas)
    ("area_ha", "Área analisada", "ha", 2), ("scene_date", "Data da cena", "", None), ("valid_fraction", "Pixels úteis (sem nuvem)", "fração", 2),
    ("ndvi_mean", "NDVI médio", "", 3), ("ndvi_median", "NDVI mediano", "", 3), ("ndvi_std", "NDVI desvio", "", 3),
    ("ndvi_p10", "NDVI percentil 10", "", 3), ("ndvi_p90", "NDVI percentil 90", "", 3), ("ndvi_ref_mean", "NDVI da vizinhança (média)", "", 3),
    ("ndvi_ref_std", "NDVI da vizinhança (desvio)", "", 3), ("ndmi_mean", "NDMI médio (umidade)", "", 3), ("ndre_mean", "NDRE médio (clorofila)", "", 3),
    ("moisture_class", "Classe de umidade", "", None), ("elevation_m", "Elevação", "m", 0), ("slope_mean_pct", "Declividade média", "%", 1),
    ("slope_max_pct", "Declividade máxima", "%", 1), ("aspect_label", "Encosta voltada para", "", None), ("tpi_min", "TPI mínimo (baixada)", "m", 1),
    ("tpi_max", "TPI máximo (topo)", "m", 1), ("frost_relief_offset_c", "Ajuste de geada pelo relevo", "°C", 1), ("weak_area_pct", "Área fraca", "%", 1),
    ("weak_area_dir", "Direção da área fraca", "", None), ("erosion_index", "Índice de erosão", "0-1", 3), ("erosion_class", "Classe de erosão", "", None),
    ("clay_pct", "Argila (0-5 cm, estimada)", "%", 0), ("ph", "pH (estimado)", "", 1), ("engine", "Motor de cálculo", "", None),
]


def _stats_block(s: dict) -> str:
    rows = []
    for k, lbl, unit, nd in STAT_LABELS:
        if k not in s or s[k] is None:
            continue
        v = s[k]
        val = f"{v:.{nd}f}" if isinstance(v, (int, float)) and nd is not None and not isinstance(v, bool) else str(v)
        rows.append(f"<tr><td>{esc(lbl)}</td><td>{esc(val)}</td><td>{esc(unit)}</td><td><code>{esc(k)}</code></td></tr>")
    return ('<div class="tw"><table><tr><th>Medida</th><th>Valor</th><th>Unidade</th><th>Campo no arquivo de dados</th></tr>'
            + "".join(rows) + "</table></div>")


def _hours_block(hrs: list[dict]) -> str:
    if not hrs:
        return ""
    def yes(b):
        return '<span class="ok">sim</span>' if b else '<span class="small">não</span>'
    trs = "".join(f'<tr><td>{esc(_fmt_dt(h["hora"]))}</td><td>{h["temp_c"]:.1f}</td><td>{h["ur_pct"]:.0f}</td><td>{h["vento_kmh"]:.1f}</td>'
                  f'<td>{h["chuva_prob_pct"]:.0f}</td><td>{h["chuva_mm"]:.1f}</td><td>{"" if h["et0_mm"] is None else f"{h["et0_mm"]:.2f}"}</td>'
                  f'<td>{h["delta_t"]:.1f}</td><td>{yes(h["serve_pulverizar"])}</td><td>{"<span class=nok>sim</span>" if h["geada"] else "não"}</td></tr>'
                  for h in hrs)
    ok = sum(1 for h in hrs if h["serve_pulverizar"])
    return (f'<p>{len(hrs)} horas de previsão; {ok} horas atendem a todos os critérios de pulverização; '
            f'{sum(1 for h in hrs if h["geada"])} horas abaixo do limite de geada.</p>'
            '<details><summary>Ver a tabela hora a hora</summary><div class="tw"><table><tr><th>Hora</th><th>°C</th><th>UR %</th><th>Vento km/h</th>'
            '<th>Chuva %</th><th>Chuva mm</th><th>ET0 mm</th><th>Delta T</th><th>Serve p/ pulverizar</th><th>Geada</th></tr>'
            + trs + "</table></div></details>")


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def _monthly_block(m: Optional[dict], fonte: Optional[str]) -> str:
    if not m:
        return ""
    keys = sorted(m, key=lambda k: int(k))
    trs = "".join(f'<tr><td>{MESES[int(k) - 1]}</td><td>{m[k].get("temp", 0):.1f}</td><td>{m[k].get("rain", 0):.0f}</td>'
                  f'<td>{"" if m[k].get("frost_days") is None else f"{m[k]["frost_days"]:.1f}"}</td></tr>' for k in keys)
    return (f'<p class="small">Fonte: {esc("simulado (demonstração)" if fonte == "simulado" else "Open-Meteo Archive (ERA5), 5 anos")}. '
            'Base da nota de viabilidade (temperatura, chuva e geadas do ciclo).</p>'
            '<div class="tw"><table><tr><th>Mês</th><th>Temperatura média °C</th><th>Chuva média mm</th><th>Dias de geada/ano</th></tr>'
            + trs + "</table></div>")


def _history_block(h: dict) -> str:
    ref, safras = h.get("referencia_vigor"), h.get("safras") or []
    parts = []
    if ref:
        nome = {"historico": "safras anteriores do mesmo talhão e cultura", "serie_recente": "série recente desta safra"}.get(ref.get("referencia"), ref.get("referencia"))
        parts.append(f'<p><b>Referência de vigor usada:</b> {esc(nome)}: média {ref["mean"]:.3f}, desvio {ref["std"]:.3f}, {ref["n"]} observações.</p>')
    else:
        parts.append('<p><b>Referência de vigor usada:</b> sem histórico suficiente do talhão (precisa de 3 observações de safras anteriores na mesma fase, '
                     'ou 4 da safra atual): a referência é a vizinhança da cena, com confiança baixa.</p>')
    if safras:
        trs = "".join(f'<tr><td>{esc(s["crop"])}</td><td>{esc(s["start_date"] or "")}</td><td>{esc(s["end_date"] or "em andamento")}</td>'
                      f'<td>{s["n_observacoes"]}</td><td>{"" if s["ndvi_pico"] is None else s["ndvi_pico"]}</td><td>{esc(s["data_pico"] or "")}</td>'
                      f'<td>{"" if s["ndvi_medio"] is None else s["ndvi_medio"]}</td><td>{"" if s["yield_t_ha"] is None else s["yield_t_ha"]}</td></tr>' for s in safras)
        parts.append('<div class="tw"><table><tr><th>Cultura</th><th>Plantio</th><th>Fim</th><th>Observações</th><th>NDVI pico</th><th>Data do pico</th>'
                     f'<th>NDVI médio</th><th>Produtividade t/ha</th></tr>{trs}</table></div>')
        serie = [(d, v) for s in safras for d, v in s.get("serie", [])]
        if serie:
            parts.append('<details><summary>Ver todas as observações (data, NDVI)</summary><p class="small">'
                         + ", ".join(f"{esc(d)}: {v:.3f}" for d, v in serie) + "</p></details>")
    return "".join(parts)


def _method_block(ms: list[dict], versao: str) -> str:
    rows = "".join(f'<tr><td><b>{esc(m["nome"])}</b></td><td><code>{esc(m["formula"])}</code></td><td>{esc(m["parametros"])}</td></tr>' for m in ms)
    return (f'<p class="small">Versão das regras: {esc(str(versao))}. Os números abaixo são lidos dos mesmos arquivos que o programa usa (rules.yaml e crops.yaml).</p>'
            f'<div class="tw"><table><tr><th>Etapa</th><th>Fórmula</th><th>Parâmetros em uso</th></tr>{rows}</table></div>')


def render_history(items: list[dict], base_url: str) -> str:
    """Linha do tempo dos avisos (mais novo primeiro), só leitura. Cada item liga ao relatório detalhado, se ainda valer."""
    nomes = {"pulverizacao": "Pulverização", "geada": "Geada", "estresse": "Estresse da lavoura", "colheita": "Colheita"}
    cards = []
    for it in items:
        txt = it["content"].split("\n\nDetalhes")[0]  # o link sai do texto; entra de novo como botão
        ver = (f'<p><a href="{esc(base_url)}/r/{esc(it["report_token"])}">Ver dados, mapas e o porquê</a></p>'
               if it.get("report_token") else "")
        cards.append(f'<div class="card"><h3>{nomes.get(it["type"], esc(it["type"] or "Aviso"))} · {esc(_fmt_dt(it["created_at"]))}</h3>'
                     f'<div class="msg">{esc(txt)}</div><p class="small">Confiança: {esc(it["confidence"] or "-")} · estado: {esc(it["state"])}</p>{ver}</div>')
    body = "".join(cards) or "<p>Ainda não houve avisos. O BALK só manda mensagem quando há uma decisão a tomar.</p>"
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex,nofollow"><title>BALK · histórico</title><style>{CSS}</style></head><body>'
            '<header><h1>BALK · histórico dos avisos</h1><p>Somente leitura. Estimativas orientativas; não substituem um engenheiro agrônomo.</p></header>'
            f'<main><section><h2>Linha do tempo</h2>{body}</section></main>'
            '<footer>Para parar de receber avisos, responda SAIR na conversa.</footer></body></html>')


def render_page(d: dict, img_dir: Optional[Path] = None, img_base: str = "img", inline: bool = False,
                expires_at: Optional[str] = None) -> str:
    sim = d.get("simulado")
    p = d["produtor"]
    parts = [f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<meta name="robots" content="noindex,nofollow"><title>BALK · relatório detalhado</title><style>{CSS}</style></head><body>']
    parts.append(f'<header><h1>BALK · relatório detalhado</h1><p>Análise de {esc(_fmt_dt(d["gerado_em"]))}'
                 + (f" · talhão {esc(d['talhao']['nome'])} ({d['talhao']['area_ha']:.1f} ha)" if d.get("talhao") else "")
                 + f" · local aproximado ({p['lat']}, {p['lon']}: precisão de cerca de 1 km)"
                 + (f" · área analisada de {d['area_ha']:.1f} ha" if d.get("area_ha") else "")
                 + (f" · link válido até {esc(_fmt_dt(expires_at))}" if expires_at else "") + "</p></header><main>")
    if sim:
        parts.append('<div class="aviso sim">Atenção: parte dos dados deste relatório é SIMULADA (modo demonstração). Não use para decidir nada na lavoura.</div>')
    parts.append('<div class="aviso">Estimativa orientativa a partir de dados de satélite e clima. Não substitui um engenheiro agrônomo. '
                 'Não indicamos produto nem dose.</div>')
    if p["precisao"] == "municipio":
        parts.append('<div class="aviso">Seu cadastro é por município (centro da cidade, não a lavoura): por isso só há análise de clima. '
                     "Envie o pin de localização da lavoura para receber mapas e a nota de viabilidade.</div>")

    secoes = []  # (id, título, html): numeradas na ordem e listadas no índice

    def sec(sid: str, titulo: str, html: str) -> None:
        if html:
            secoes.append((sid, titulo, html))

    msgs = "".join(f'<div class="msg">{esc(m["texto"])}</div>' for m in d["mensagens"])
    sec("mensagens", "O que enviamos ao produtor", f'{msgs}<p class="small">A mensagem é curta de propósito. As seções abaixo mostram os dados e as contas por trás dela.</p>')
    if d.get("conclusoes"):
        sec("conclusoes", "Conclusões (resumo para o técnico)", "<ul>" + "".join(f"<li>{esc(c)}</li>" for c in d["conclusoes"]) + "</ul>")

    rows = "".join(f'<tr><td>{esc(r["camada"])}</td><td>{esc(r["fonte"])}</td><td>{esc(r["data"] or "")}</td><td>{esc(r["resolucao"])}</td>'
                   f'<td>{esc(r["valor"])}<br><span class="small">{esc(r["nota"])}</span></td></tr>' for r in d["dados"])
    sec("dados", "Os dados que coletamos", f'<div class="tw"><table><tr><th>Camada</th><th>Fonte</th><th>Data</th><th>Resolução</th>'
                                          f'<th>O que mostrou na sua área</th></tr>{rows}</table></div>')
    if d.get("estatisticas"):
        sec("estatisticas", "Estatísticas completas da área", _stats_block(d["estatisticas"]))

    imgs = {i["arquivo"][:-4]: i for i in d.get("imagens", [])}
    maps = [imgs[k] for k in ("ndvi", "ndmi", "slope", "tpi", "zonas", "anomalia", "erosao") if k in imgs]
    if maps:
        sec("mapas", "Mapas da área", "<p class=\"small\">Cada mapa mostra uma camada, no estilo de um projeto de SIG: "
                                      "contorno tracejado = área analisada, barra de escala, norte e legenda.</p>"
                                      + "".join(_figure(i, img_dir, img_base, inline) for i in maps))
    if d["culturas"]:
        body = "".join(_crop_block(c) for c in d["culturas"])
        fig = _figure(imgs["fatores"], img_dir, img_base, inline) if "fatores" in imgs else ""
        sec("notas", "Por que estas notas", f"{fig}{body}")
    if d["relacoes"]:
        sec("relacoes", "Como as camadas se combinam", _relations_block(d["relacoes"]))
    fig = _figure(imgs["clima"], img_dir, img_base, inline) if "clima" in imgs else ""
    if d["alertas"]:
        sec("alertas", "Alertas e por que foram enviados", fig + "".join(_alert_block(a) for a in d["alertas"]))
    elif fig:
        sec("alertas", "Clima das próximas 72 horas", fig + "<p>Nenhum alerta novo agora: o BALK só avisa quando há uma decisão a tomar.</p>")
    sec("horas", "Clima hora a hora (com as contas das regras)", _hours_block(d.get("clima_horas") or []))
    sec("mensal", "Clima histórico por mês", _monthly_block(d.get("clima_mensal"), d.get("clima_mensal_fonte")))
    if d.get("historico") and (d["historico"].get("safras") or d.get("estatisticas")):
        sec("historico", "Histórico do talhão (safras e observações)", _history_block(d["historico"]))
    if "modelo" in imgs:
        sec("modelo", "Como o BALK pensou", _figure(imgs["modelo"], img_dir, img_base, inline))
    if d.get("metodo"):
        sec("metodo", "Método: fórmulas e parâmetros", _method_block(d["metodo"], d.get("versao_regras", "")))
    if not inline:
        sec("baixar", "Baixar os dados", '<p>Para analisar em planilha, em SIG ou com outro algoritmo:</p><ul>'
                                          f'<li><a href="{esc(img_base.rsplit("/img", 1)[0])}/dados.json">Todos os dados deste relatório (JSON)</a>: estatísticas, notas fator a fator, '
                                          'critérios de cada alerta, clima hora a hora e mensal, histórico e método.</li>'
                                          f'<li><a href="{esc(img_base.rsplit("/img", 1)[0])}/clima.csv">Clima hora a hora (CSV)</a>, com Delta T e as horas que servem para pulverizar.</li>'
                                          f'<li><a href="{esc(img_base.rsplit("/img", 1)[0])}/baixar">Esta página em um arquivo só (HTML com as imagens)</a>.</li></ul>'
                                          '<p class="small">A localização exata do talhão não vai no arquivo: só a área, as estatísticas e as contas.</p>')
    lim = "".join(f"<li>{esc(x)}</li>" for x in d["limites"])
    sec("limites", "Limites: o que isto não é", f"<ul>{lim}</ul>")

    indice = " · ".join(f'<a href="#{sid}">{i}. {esc(t)}</a>' for i, (sid, t, _) in enumerate(secoes, 1))
    parts.append(f'<nav class="indice"><b>Neste relatório:</b> {indice}</nav>')
    for i, (sid, titulo, html) in enumerate(secoes, 1):
        parts.append(f'<section id="{sid}"><h2>{i}. {esc(titulo)}</h2>{html}</section>')
    parts.append("</main>")
    atr = "".join(f"<li>{esc(a)}</li>" for a in d["atribuicoes"])
    parts.append(f"<footer><b>Fontes e atribuições</b><ul>{atr}</ul>Relatório gerado automaticamente pelo BALK. Guarde o link: "
                 "ele é pessoal e expira. Para falar com um agrônomo, responda 2 na conversa.</footer></body></html>")
    return "".join(parts)
