import { api, ApiError, el, mostrarErro, fmtData } from "/app/js/api.js";

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";

function linha(serie) {
  // Mini gráfico do NDVI da safra (0 a 1) em SVG, sem biblioteca.
  const w = 300, h = 70, pad = 6;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Evolução do índice de vegetação nesta safra");
  svg.style.width = "100%"; svg.style.maxWidth = "420px";
  if (serie.length < 2) return null;
  const xs = serie.map((_, i) => pad + (i * (w - 2 * pad)) / (serie.length - 1));
  const ys = serie.map(([, v]) => h - pad - Math.max(0, Math.min(1, v)) * (h - 2 * pad));
  const p = document.createElementNS(NS, "polyline");
  p.setAttribute("points", xs.map((x, i) => `${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" "));
  p.setAttribute("fill", "none"); p.setAttribute("stroke", "#1f6f43"); p.setAttribute("stroke-width", "2.5");
  svg.append(p);
  return svg;
}

function cartao(s) {
  const fechada = !!s.end_date;
  const caixa = el("div", { class: "card" });
  caixa.append(el("h3", { text: `${s.plot_name} · ${s.crop}` }));
  caixa.append(el("p", { class: "suave", text: `Plantio em ${fmtData(s.start_date)}` + (fechada ? ` · fechada em ${fmtData(s.end_date)}` : " · em andamento") }));
  const dados = [];
  if (s.ndvi_pico != null) dados.push(`Pico do índice de vegetação: ${s.ndvi_pico.toLocaleString("pt-BR")} em ${fmtData(s.data_pico)}`);
  if (s.ndvi_medio != null) dados.push(`Média: ${s.ndvi_medio.toLocaleString("pt-BR")}`);
  dados.push(`${s.n_observacoes} imagem(ns) de satélite usada(s)`);
  if (s.yield_t_ha != null) dados.push(`Produtividade informada: ${s.yield_t_ha.toLocaleString("pt-BR")} t/ha`);
  for (const d of dados) caixa.append(el("p", { text: d }));
  const g = linha(s.serie);
  if (g) caixa.append(g);
  if (!fechada) {
    const campo = el("input", { type: "number", min: "0.1", max: "150", step: "0.1", inputmode: "decimal", "aria-label": "Produtividade em toneladas por hectare", placeholder: "t/ha" });
    const erro = el("p", { class: "erro escondido", role: "alert" });
    const b = el("button", { class: "btn sec peq", type: "button", text: "Fechar a safra" });
    b.addEventListener("click", async () => {
      const v = parseFloat(String(campo.value).replace(",", "."));
      if (!(v > 0)) { erro.textContent = "Digite a produtividade em toneladas por hectare, ex.: 3,4."; erro.classList.remove("escondido"); return; }
      try { await api(`/seasons/${s.id}/close`, { method: "POST", body: { yield_t_ha: v } }); carregar(); } catch (e) { mostrarErro(erro, e); }
    });
    caixa.append(el("label", { text: "Produtividade (t/ha) para fechar a safra" }), campo, el("p", { class: "barra" }, b), erro);
  }
  return caixa;
}

async function carregar() {
  let h;
  try { h = await api("/history"); } catch (e) {
    if (e instanceof ApiError && e.status === 401) { $("semSessao").classList.remove("escondido"); return; }
    mostrarErro($("erroGeral"), e);
    return;
  }
  const ct = $("safras");
  ct.replaceChildren();
  if (!h.safras.length) ct.append(el("p", { class: "suave", text: "Ainda não há safras. Elas abrem sozinhas quando o talhão tem cultura e data de plantio." }));
  for (const s of h.safras) ct.append(cartao(s));
  const av = $("avisos");
  av.replaceChildren();
  if (!h.avisos.length) av.append(el("p", { class: "suave", text: "Nenhum aviso enviado ainda. O BALK fala pouco de propósito." }));
  for (const a of h.avisos) av.append(el("div", { class: "msg" }, el("small", { class: "suave", text: fmtData(a.at) + " · " + a.type }), el("div", { text: a.text })));
}

carregar();
