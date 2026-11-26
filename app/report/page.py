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
main{max-width:920px;margin:auto;padding:12px}section{background:#fff;border-radius:14px;box-shadow:0 1px 4px #0002;padding:16px;margin:12px 0}
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
    teto = "<p class=\"small\">Algum fator zerou, então a nota máxima desta cultura é 40.</p>" if c["teto_40"] else ""
    tag = " (a sua cultura)" if c["informada"] else ""
    return (f'<div class="card"><h3>{esc(c["crop"].capitalize())}{tag}: nota {c["nota"]}/100, confiança {esc(c["confianca"])}</h3>'
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

    msgs = "".join(f'<div class="msg">{esc(m["texto"])}</div>' for m in d["mensagens"])
    parts.append(f"<section><h2>1. O que enviamos a você</h2>{msgs}<p class=\"small\">As seções abaixo mostram os dados e as contas por trás destas mensagens.</p></section>")

    rows = "".join(f'<tr><td>{esc(r["camada"])}</td><td>{esc(r["fonte"])}</td><td>{esc(r["data"] or "")}</td><td>{esc(r["resolucao"])}</td>'
                   f'<td>{esc(r["valor"])}<br><span class="small">{esc(r["nota"])}</span></td></tr>' for r in d["dados"])
    parts.append(f'<section><h2>2. Os dados que coletamos</h2><div class="tw"><table><tr><th>Camada</th><th>Fonte</th><th>Data</th><th>Resolução</th>'
                 f'<th>O que mostrou na sua área</th></tr>{rows}</table></div></section>')

    imgs = {i["arquivo"][:-4]: i for i in d.get("imagens", [])}
    maps = [imgs[k] for k in ("ndvi", "ndmi", "slope", "tpi", "zonas", "anomalia", "erosao") if k in imgs]
    if maps:
        parts.append("<section><h2>3. Mapas da sua área</h2><p class=\"small\">Cada mapa mostra uma camada, no estilo de um projeto de SIG: "
                     "contorno tracejado = área analisada, barra de escala, norte e legenda.</p>"
                     + "".join(_figure(i, img_dir, img_base, inline) for i in maps) + "</section>")
    if d["culturas"]:
        body = "".join(_crop_block(c) for c in d["culturas"])
        fig = _figure(imgs["fatores"], img_dir, img_base, inline) if "fatores" in imgs else ""
        parts.append(f"<section><h2>4. Por que estas notas</h2>{fig}{body}</section>")
    if d["relacoes"]:
        parts.append(f'<section><h2>5. Como as camadas se combinam</h2>{_relations_block(d["relacoes"])}</section>')
    if d["alertas"]:
        fig = _figure(imgs["clima"], img_dir, img_base, inline) if "clima" in imgs else ""
        parts.append(f'<section id="alertas"><h2>6. Alertas e por que foram enviados</h2>{fig}{"".join(_alert_block(a) for a in d["alertas"])}</section>')
    elif "clima" in imgs:
        parts.append(f'<section id="alertas"><h2>6. Clima das próximas 72 horas</h2>{_figure(imgs["clima"], img_dir, img_base, inline)}'
                     "<p>Nenhum alerta novo agora: o BALK só avisa quando há uma decisão a tomar.</p></section>")
    if "modelo" in imgs:
        parts.append(f'<section><h2>7. Como o BALK pensou</h2>{_figure(imgs["modelo"], img_dir, img_base, inline)}</section>')
    lim = "".join(f"<li>{esc(x)}</li>" for x in d["limites"])
    parts.append(f"<section><h2>8. Limites: o que isto não é</h2><ul>{lim}</ul></section></main>")
    atr = "".join(f"<li>{esc(a)}</li>" for a in d["atribuicoes"])
    parts.append(f"<footer><b>Fontes e atribuições</b><ul>{atr}</ul>Relatório gerado automaticamente pelo BALK. Guarde o link: "
                 "ele é pessoal e expira. Para falar com um agrônomo, responda 2 na conversa.</footer></body></html>")
    return "".join(parts)
