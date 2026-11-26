// Mapa para desenhar talhões: MapLibre (mapa) + Terra Draw (desenho e edição de vértices) + Turf (área e cruzamento de linhas).
// O navegador valida para ajudar; quem decide é o servidor (a mesma checagem roda lá, em Python).
import * as maplibregl from "/app/vendor/maplibre-gl.mjs";
import { api, ApiError, el, mostrarErro, limparErro, fmtHa } from "/app/js/api.js";

const $ = (id) => document.getElementById(id);
const TD = window.terraDraw;
const ADP = window.terraDrawMaplibreGlAdapter;

let cfg, map, draw;
let talhoes = [];            // do servidor: {id, name, area_ha, crop, planting_date, geometry}
const porFeature = new Map(); // id do Terra Draw -> id do talhão no servidor (ou null se ainda não salvo)
let atual = null;             // id do Terra Draw em edição
let entregaModo = false, entregaMarker = null, entrega = null;

function geomDe(featureId) {
  const f = draw.getSnapshot().find((x) => x.id === featureId);
  return f ? f.geometry : null;
}

function validarLocal(geometry) {
  const erros = [];
  const f = { type: "Feature", properties: {}, geometry };
  const ha = turf.area(f) / 10000;
  const lim = cfg.limites;
  if (ha < lim.area_min_ha) erros.push(`Área de ${fmtHa(ha)}: abaixo do mínimo de ${lim.area_min_ha} ha.`);
  if (ha > lim.area_max_ha) erros.push(`Área de ${fmtHa(ha)}: acima do máximo de ${lim.area_max_ha} ha.`);
  try { if (turf.kinks(f).features.length > 0) erros.push("As linhas do desenho se cruzam. Ajuste os cantos."); } catch (e) { /* sem checagem local */ }
  const [x0, y0, x1, y1] = cfg.brasil_bbox;
  const fora = geometry.coordinates[0].some(([lon, lat]) => lon < x0 || lon > x1 || lat < y0 || lat > y1);
  if (fora) erros.push("O desenho está fora do Brasil.");
  return { ha, erros };
}

function mostrarForm(featureId) {
  atual = featureId;
  const g = geomDe(featureId);
  const sid = porFeature.get(featureId);
  const t = talhoes.find((x) => x.id === sid);
  $("form").classList.remove("escondido");
  $("formTitulo").textContent = sid ? "Editar talhão" : "Novo talhão";
  $("btnSalvar").textContent = sid ? "Salvar alterações" : "Salvar talhão";
  $("btnExcluir").classList.toggle("escondido", !sid);
  $("nome").value = t ? t.name : `Talhão ${talhoes.length + 1}`;
  $("cultura").value = t && t.crop ? t.crop : "";
  $("plantio").value = t && t.planting_date ? t.planting_date : "";
  limparErro($("erroForm"));
  atualizarArea(g);
  renderLista();
}

function atualizarArea(g) {
  if (!g) { $("area").textContent = ""; return; }
  const { ha, erros } = validarLocal(g);
  $("area").textContent = "Área: " + fmtHa(ha);
  if (erros.length) { $("erroForm").textContent = erros.join(" "); $("erroForm").classList.remove("escondido"); }
  else limparErro($("erroForm"));
}

function fecharForm() {
  atual = null;
  $("form").classList.add("escondido");
  renderLista();
}

function renderLista() {
  const ul = $("lista");
  ul.replaceChildren();
  for (const [fid, sid] of porFeature) {
    const t = talhoes.find((x) => x.id === sid);
    const nome = t ? t.name : "Novo talhão (não salvo)";
    const sub = t ? `${fmtHa(t.area_ha)}${t.crop ? " · " + t.crop : ""}` : "Preencha o nome e salve.";
    const b = el("button", { class: "talhao-item" + (fid === atual ? " sel" : ""), type: "button" }, el("strong", { text: nome }), el("small", { text: sub }));
    b.addEventListener("click", () => { draw.setMode("select"); draw.selectFeature(fid); mostrarForm(fid); });
    ul.append(el("li", {}, b));
  }
  if (!porFeature.size) ul.append(el("li", { class: "suave", text: "Nenhum talhão ainda." }));
}

async function carregarTalhoes(ajustar) {
  const r = await api("/plots");
  talhoes = r.talhoes;
  draw.clear();
  porFeature.clear();
  if (talhoes.length) {
    const res = draw.addFeatures(talhoes.map((t) => ({ type: "Feature", properties: { mode: "polygon" }, geometry: t.geometry })));
    res.forEach((x, i) => { if (x.valid) porFeature.set(x.id, talhoes[i].id); });
    if (ajustar) {
      const [a, b, c, d] = turf.bbox({ type: "FeatureCollection", features: talhoes.map((t) => ({ type: "Feature", properties: {}, geometry: t.geometry })) });
      map.fitBounds([[a, b], [c, d]], { padding: 60, maxZoom: 17, duration: 0 });
    }
  }
  draw.setMode("static");
  fecharForm();
}

function iniciarMapa() {
  const camadas = cfg.mapa.layers;  // a primeira é a inicial (satélite, se houver chave do MapTiler)
  const sources = {}, layers = [];
  camadas.forEach((c, i) => {
    sources[c.id] = { type: "raster", tiles: [c.url], tileSize: 256, maxzoom: c.max_zoom, attribution: c.attribution };
    layers.push({ id: c.id, type: "raster", source: c.id, layout: { visibility: i === 0 ? "visible" : "none" } });
  });
  map = new maplibregl.Map({
    container: "mapa", center: [-52, -14], zoom: 4, attributionControl: { compact: true },
    style: { version: 8, sources, layers },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
  // Não espera as imagens do mapa (se o provedor falhar, o desenho dos talhões ainda tem que funcionar): basta o estilo.
  return new Promise((ok) => { map.once("style.load", () => { configurarCamadas(camadas); ok(); }); setTimeout(ok, 6000); });
}

function configurarCamadas(camadas) {
  if (camadas.length > 1) {  // alternar entre satélite e ruas
    const b = $("btnCamada");
    b.classList.remove("escondido");
    let atualId = camadas[0].id;
    const rotulo = () => { b.textContent = "Ver: " + camadas.find((c) => c.id !== atualId).nome; };
    const trocar = () => {
      const prox = camadas.find((c) => c.id !== atualId);
      map.setLayoutProperty(atualId, "visibility", "none");
      map.setLayoutProperty(prox.id, "visibility", "visible");
      atualId = prox.id;
      rotulo();
    };
    rotulo();
    b.addEventListener("click", trocar);
    let avisou = false;
    map.on("error", (e) => {  // chave inválida, cota do plano gratuito esgotada ou sem internet: volta para as ruas e avisa
      if (avisou || e.sourceId !== camadas[0].id || atualId !== camadas[0].id) return;
      avisou = true;
      trocar();
      $("erroGeral").textContent = "A imagem de satélite não carregou agora. Mostrando o mapa de ruas.";
      $("erroGeral").classList.remove("escondido");
    });
  }
}

function iniciarDesenho() {
  const estilo = { fillColor: "#1f6f43", fillOpacity: 0.3, outlineColor: "#14502f", outlineWidth: 3 };
  draw = new TD.TerraDraw({
    adapter: new ADP.TerraDrawMapLibreGLAdapter({ map, lib: maplibregl }),
    modes: [
      new TD.TerraDrawPolygonMode({ styles: estilo }),
      new TD.TerraDrawSelectMode({
        styles: { selectedPolygonColor: "#f2b705", selectedPolygonFillOpacity: 0.3, selectedPolygonOutlineColor: "#8a6100", selectedPolygonOutlineWidth: 3,
                  selectionPointColor: "#ffffff", selectionPointOutlineColor: "#8a6100", midPointColor: "#f2b705" },
        flags: { polygon: { feature: { draggable: true, rotateable: false, scaleable: false,
                 coordinates: { midpoints: true, draggable: true, deletable: true } } } },
      }),
    ],
  });
  draw.start();
  draw.on("finish", (id, ctx) => {
    if (ctx.action === "draw") {          // acabou de fechar um polígono novo
      porFeature.set(id, null);
      setTimeout(() => { draw.setMode("select"); draw.selectFeature(id); mostrarForm(id); }, 0);
    } else if (id === atual) {            // moveu o talhão ou um canto: confere a área de novo
      atualizarArea(geomDe(id));
    }
  });
  draw.on("select", (id) => { if (porFeature.has(id)) mostrarForm(id); });
}

async function salvar(ev) {
  ev.preventDefault();
  limparErro($("erroForm"));
  const g = geomDe(atual);
  if (!g) return;
  const { erros } = validarLocal(g);
  if (erros.length) { $("erroForm").textContent = erros.join(" "); $("erroForm").classList.remove("escondido"); return; }
  if (!$("nome").value.trim()) { $("erroForm").textContent = "Dê um nome ao talhão."; $("erroForm").classList.remove("escondido"); return; }
  const body = { name: $("nome").value.trim(), geometry: g, crop: $("cultura").value || null, planting_date: $("plantio").value || null };
  const sid = porFeature.get(atual);
  $("btnSalvar").disabled = true;
  try {
    await api(sid ? `/plots/${sid}` : "/plots", { method: sid ? "PUT" : "POST", body });
    await carregarTalhoes(false);
  } catch (e) {
    mostrarErro($("erroForm"), e);  // o servidor também confere: sobreposição, limites, cultura e data
  } finally {
    $("btnSalvar").disabled = false;
  }
}

async function cancelar() {
  await carregarTalhoes(false);  // descarta o desenho não salvo e volta ao que está no servidor
}

async function excluir() {
  const sid = porFeature.get(atual);
  if (!sid || !confirm("Excluir este talhão? O histórico dele também será apagado.")) return;
  try { await api(`/plots/${sid}`, { method: "DELETE" }); await carregarTalhoes(false); } catch (e) { mostrarErro($("erroForm"), e); }
}

async function buscar() {
  const q = $("busca").value.trim();
  const caixa = $("resultados");
  caixa.replaceChildren();
  if (q.length < 2) return;
  const m = q.replace(",", " ").match(/^\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$/);
  if (m) { map.flyTo({ center: [parseFloat(m[2]), parseFloat(m[1])], zoom: 15 }); return; }
  try {
    const r = await api("/geocode?q=" + encodeURIComponent(q));
    if (!r.resultados.length) { caixa.append(el("p", { class: "suave", text: "Não achei esse lugar. Tente o município ou lat, lon." })); return; }
    for (const x of r.resultados) {
      const b = el("button", { type: "button", text: x.nome + (x.regiao ? " — " + x.regiao : "") });
      b.addEventListener("click", () => { map.flyTo({ center: [x.lon, x.lat], zoom: 13 }); caixa.replaceChildren(); });
      caixa.append(b);
    }
  } catch (e) { mostrarErro($("erroGeral"), e); }
}

function gps() {
  if (!navigator.geolocation) { $("erroGeral").textContent = "Este aparelho não informa a localização."; $("erroGeral").classList.remove("escondido"); return; }
  navigator.geolocation.getCurrentPosition(
    (p) => map.flyTo({ center: [p.coords.longitude, p.coords.latitude], zoom: 15 }),  // só centra: não define limites
    () => { $("erroGeral").textContent = "Não consegui sua localização. Use a busca."; $("erroGeral").classList.remove("escondido"); },
    { enableHighAccuracy: true, timeout: 10000 });
}

function marcarEntrega(lat, lon) {
  entrega = { lat, lon };
  if (entregaMarker) entregaMarker.remove();
  entregaMarker = new maplibregl.Marker({ color: "#8a5a2b" }).setLngLat([lon, lat]).addTo(map);
  $("entregaTxt").textContent = `Ponto marcado: ${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}

async function concluir() {
  limparErro($("erroFim"));
  $("okFim").classList.add("escondido");
  if ([...porFeature.values()].some((v) => v === null)) {
    $("erroFim").textContent = "Há um desenho sem salvar. Salve ou cancele antes de concluir.";
    $("erroFim").classList.remove("escondido");
    return;
  }
  $("btnConcluir").disabled = true;
  try {
    const me = { farm_name: $("fazenda").value.trim() || null };
    if (entrega) { me.delivery_lat = entrega.lat; me.delivery_lon = entrega.lon; me.delivery_name = "Ponto de entrega"; }
    await api("/me", { method: "PUT", body: me });
    const r = await api("/finish", { method: "POST", body: { enviar_relatorio: false } });
    $("okFim").textContent = r.relatorio_a_caminho
      ? `Pronto! ${r.talhoes} talhão(ões) cadastrado(s). Em instantes chega um relatório de cada um no seu WhatsApp.`
      : `Salvo. ${r.talhoes} talhão(ões) no cadastro.`;
    $("okFim").classList.remove("escondido");
  } catch (e) { mostrarErro($("erroFim"), e); } finally { $("btnConcluir").disabled = false; }
}

async function iniciar() {
  try {
    const me = await api("/me");
    $("fazenda").value = (me.farm && me.farm.name) || "";
    if (me.farm && me.farm.delivery_lat != null) { entrega = { lat: me.farm.delivery_lat, lon: me.farm.delivery_lon }; }
    cfg = await api("/config");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) { location.href = "/app/cadastro.html"; return; }
    mostrarErro($("erroGeral"), e);
    return;
  }
  for (const c of cfg.culturas) $("cultura").append(el("option", { value: c, text: c.charAt(0).toUpperCase() + c.slice(1) }));
  $("plantio").max = new Date().toISOString().slice(0, 10);
  await iniciarMapa();
  iniciarDesenho();
  if (["localhost", "127.0.0.1"].includes(location.hostname)) window.__balk = { map, draw, porFeature };  // só para teste local
  if (entrega) marcarEntrega(entrega.lat, entrega.lon);
  await carregarTalhoes(true);

  $("btnDesenhar").addEventListener("click", () => { entregaModo = false; fecharForm(); draw.setMode("polygon"); });
  $("form").addEventListener("submit", salvar);
  $("btnCancelar").addEventListener("click", cancelar);
  $("btnExcluir").addEventListener("click", excluir);
  $("btnBuscar").addEventListener("click", buscar);
  $("busca").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); buscar(); } });
  $("btnGps").addEventListener("click", gps);
  $("btnConcluir").addEventListener("click", concluir);
  $("btnEntrega").addEventListener("click", () => { entregaModo = true; draw.setMode("static"); $("entregaTxt").textContent = "Toque no mapa onde entrega a colheita."; });
  map.on("click", (e) => { if (entregaModo) { entregaModo = false; marcarEntrega(e.lngLat.lat, e.lngLat.lng); } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && atual && !porFeature.get(atual)) cancelar(); });
}

iniciar().catch((e) => {
  console.error("mapa:", e);
  $("erroGeral").textContent = "Não consegui abrir o mapa. Recarregue a página.";
  $("erroGeral").classList.remove("escondido");
});
