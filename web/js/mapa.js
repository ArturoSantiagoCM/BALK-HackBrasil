// Mapa para desenhar talhões. MapLibre (mapa e camadas) + Terra Draw (mão livre, retângulo, círculo e edição dos pontos) +
// Turf (área, giro, escala, simplificação). O contorno "toque nos cantos" é próprio, para ter Desfazer, Fechar e o GPS.
// O navegador valida para ajudar; quem decide é o servidor (a mesma checagem roda lá, em Python).
import * as maplibregl from "/app/vendor/maplibre-gl.mjs";
import { api, ApiError, el, mostrarErro, limparErro, fmtHa } from "/app/js/api.js";

const $ = (id) => document.getElementById(id);
const TD = window.terraDraw;
const ADP = window.terraDrawMaplibreGlAdapter;
const MAX_PONTOS = 400;           // o servidor aceita até 500
const SATELITES = ["satelite", "satelite_maptiler", "sentinel"];

let cfg, map, draw;
let talhoes = [];                 // do servidor: {id, name, area_ha, crop, planting_date, geometry}
const porFeature = new Map();     // id do Terra Draw -> id do talhão no servidor (ou null se ainda não salvo)
const historico = new Map();      // id do Terra Draw -> geometrias anteriores (para Desfazer)
const ultima = new Map();         // id do Terra Draw -> geometria atual conhecida
const sugeridos = new Map();      // id do Terra Draw -> nome vindo do arquivo importado (ainda não salvo)
let atual = null;                 // id do Terra Draw em edição
let ferramenta = null;            // contornar | mao | retangulo | circulo | null
let rascunho = [];                // cantos do contorno em construção
let entregaModo = false, entregaMarker = null, entrega = null;
let baseAtual = null;

// ------------------------------------------------------------------ utilidades
function aviso(txt, erro = true) {
  const n = $("erroGeral");
  n.textContent = txt;
  n.classList.toggle("ok", !erro);
  n.classList.toggle("erro", erro);
  n.classList.remove("escondido");
}
function dica(txt) { $("dica").textContent = txt || ""; }
function arred(c) { return [Math.round(c[0] * 1e7) / 1e7, Math.round(c[1] * 1e7) / 1e7]; }
function poligono(coords) { return { type: "Polygon", coordinates: [coords] }; }
function nPontos(g) { return g.coordinates[0].length - 1; }

function geomDe(featureId) {
  const f = draw.getSnapshot().find((x) => x.id === featureId);
  return f ? f.geometry : null;
}

function simplificar(geom, alvo = MAX_PONTOS) {
  // Reduz os pontos (mão livre, círculo, arquivos detalhados) sem mudar a forma de forma visível: tolerância de ~1 m, subindo até caber.
  let g = geom, tol = 0.00001;
  for (let i = 0; i < 8 && nPontos(g) > alvo; i++, tol *= 2) {
    try { g = turf.simplify({ type: "Feature", properties: {}, geometry: geom }, { tolerance: tol, highQuality: true }).geometry; } catch (e) { break; }
  }
  return g;
}

function validarLocal(geometry) {
  const erros = [];
  const f = { type: "Feature", properties: {}, geometry };
  const ha = turf.area(f) / 10000;
  const lim = cfg.limites;
  if (ha < lim.area_min_ha) erros.push(`Área de ${fmtHa(ha)}: abaixo do mínimo de ${lim.area_min_ha} ha.`);
  if (ha > lim.area_max_ha) erros.push(`Área de ${fmtHa(ha)}: acima do máximo de ${lim.area_max_ha} ha.`);
  if (nPontos(geometry) > lim.max_vertices) erros.push(`Pontos demais (${nPontos(geometry)}): use Simplificar.`);
  try { if (turf.kinks(f).features.length > 0) erros.push("As linhas do desenho se cruzam. Ajuste os cantos."); } catch (e) { /* sem checagem local */ }
  const [x0, y0, x1, y1] = cfg.brasil_bbox;
  if (geometry.coordinates[0].some(([lon, lat]) => lon < x0 || lon > x1 || lat < y0 || lat > y1)) erros.push("O desenho está fora do Brasil.");
  return { ha, erros };
}

// ------------------------------------------------------------------ camadas do mapa
function montarEstilo(camadas) {
  const sources = {}, layers = [];
  const ordem = [...camadas.filter((c) => c.tipo === "base"), ...camadas.filter((c) => c.tipo === "dem"), ...camadas.filter((c) => c.tipo === "overlay")];
  for (const c of ordem) {
    if (c.tipo === "dem") {
      sources[c.id] = { type: "raster-dem", tiles: [c.url], tileSize: 256, encoding: c.encoding || "terrarium", maxzoom: c.max_zoom, attribution: c.attribution };
      layers.push({ id: c.id, type: "hillshade", source: c.id, layout: { visibility: "none" },
                    paint: { "hillshade-exaggeration": 0.55, "hillshade-shadow-color": "#1b2a1f", "hillshade-highlight-color": "#ffffff", "hillshade-illumination-direction": 315 } });
    } else {
      sources[c.id] = { type: "raster", tiles: [c.url], tileSize: 256, maxzoom: c.max_zoom, attribution: c.attribution };
      layers.push({ id: c.id, type: "raster", source: c.id, layout: { visibility: "none" } });
    }
  }
  return { version: 8, sources, layers };
}

const marcados = new Set();       // camadas por cima ligadas pelo produtor

function aplicarCamadas() {
  const eSat = SATELITES.includes(baseAtual);
  for (const c of cfg.mapa.layers) {
    if (!map.getLayer(c.id)) continue;
    let ver = false;
    if (c.tipo === "base") ver = c.id === baseAtual;
    else if (c.id === "nomes") ver = marcados.has(c.id) && eSat;  // rótulos só fazem sentido sobre imagem
    else ver = marcados.has(c.id);
    map.setLayoutProperty(c.id, "visibility", ver ? "visible" : "none");
  }
}

function montarSeletorCamadas() {
  const bases = cfg.mapa.layers.filter((c) => c.tipo === "base");
  const extras = cfg.mapa.layers.filter((c) => c.tipo !== "base");
  baseAtual = bases[0].id;
  for (const c of extras) if (c.ligada) marcados.add(c.id);
  const boxB = $("camadasBases"), boxE = $("camadasExtras");
  for (const c of bases) {
    const r = el("input", { type: "radio", name: "base", value: c.id });
    r.checked = c.id === baseAtual;
    r.addEventListener("change", () => { baseAtual = c.id; aplicarCamadas(); });
    boxB.append(el("label", {}, r, el("span", {}, el("span", { text: c.nome }), el("small", { text: c.descricao }))));
  }
  for (const c of extras) {
    const k = el("input", { type: "checkbox", value: c.id });
    k.checked = marcados.has(c.id);
    k.addEventListener("change", () => { if (k.checked) marcados.add(c.id); else marcados.delete(c.id); aplicarCamadas(); });
    boxE.append(el("label", {}, k, el("span", {}, el("span", { text: c.nome }), el("small", { text: c.descricao }))));
  }
  $("btnCamadas").addEventListener("click", () => {
    const aberto = $("camadasPainel").classList.toggle("escondido") === false;
    $("btnCamadas").setAttribute("aria-expanded", String(aberto));
  });
  aplicarCamadas();
  // Se o provedor do fundo falhar de vez (chave inválida, cota, sem internet), volta para as ruas e avisa. Poucos erros isolados não contam.
  const falhas = {};
  map.on("error", (e) => {
    const id = e.sourceId;
    if (!id || id !== baseAtual || baseAtual === "ruas") return;
    const agora = Date.now();
    falhas[id] = (falhas[id] || []).filter((t) => agora - t < 10000).concat(agora);
    if (falhas[id].length >= 6) {
      falhas[id] = [];
      const nome = (bases.find((b) => b.id === id) || {}).nome || "Esta camada";
      baseAtual = "ruas";
      document.querySelectorAll("input[name=base]").forEach((r) => { r.checked = r.value === "ruas"; });
      aplicarCamadas();
      aviso(`${nome} não carregou agora. Mostrando o mapa de ruas.`);
    }
  });
}

function iniciarMapa() {
  map = new maplibregl.Map({ container: "mapa", center: [-52, -14], zoom: 4, attributionControl: { compact: true }, style: montarEstilo(cfg.mapa.layers), maxPitch: 0 });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
  // Não espera as imagens do mapa (se o provedor falhar, o desenho dos talhões ainda tem que funcionar): basta o estilo.
  return new Promise((ok) => {
    let feito = false;
    const pronto = () => { if (feito) return; feito = true; montarSeletorCamadas(); criarRascunho(); ok(); };
    map.once("style.load", pronto);
    setTimeout(pronto, 6000);
  });
}

// ------------------------------------------------------------------ contorno por toques (cantos), com Desfazer, Fechar e GPS
function criarRascunho() {
  map.addSource("rascunho", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
  map.addLayer({ id: "rascunho-area", type: "fill", source: "rascunho", filter: ["==", ["get", "k"], "area"], paint: { "fill-color": "#1f6f43", "fill-opacity": 0.25 } });
  map.addLayer({ id: "rascunho-linha", type: "line", source: "rascunho", filter: ["==", ["get", "k"], "linha"], paint: { "line-color": "#f2b705", "line-width": 3, "line-dasharray": [2, 1] } });
  map.addLayer({ id: "rascunho-pontos", type: "circle", source: "rascunho", filter: ["==", ["get", "k"], "ponto"],
                paint: { "circle-radius": ["case", ["get", "primeiro"], 9, 6], "circle-color": ["case", ["get", "primeiro"], "#f2b705", "#ffffff"], "circle-stroke-color": "#14502f", "circle-stroke-width": 2 } });
}

function desenharRascunho() {
  const f = [];
  if (rascunho.length >= 3) f.push({ type: "Feature", properties: { k: "area" }, geometry: poligono([...rascunho, rascunho[0]]) });
  if (rascunho.length >= 2) f.push({ type: "Feature", properties: { k: "linha" }, geometry: { type: "LineString", coordinates: rascunho } });
  rascunho.forEach((p, i) => f.push({ type: "Feature", properties: { k: "ponto", primeiro: i === 0 }, geometry: { type: "Point", coordinates: p } }));
  map.getSource("rascunho").setData({ type: "FeatureCollection", features: f });
  if (ferramenta !== "contornar") return;
  if (rascunho.length < 3) dica(rascunho.length === 0 ? "Toque em cada canto da lavoura, um por um." : `${rascunho.length} ponto(s). Continue tocando nos cantos (precisa de pelo menos 3).`);
  else dica(`${rascunho.length} pontos, cerca de ${fmtHa(turf.area({ type: "Feature", properties: {}, geometry: poligono([...rascunho, rascunho[0]]) }) / 10000)}. Toque em Fechar talhão, ou no ponto amarelo.`);
}

function pontoMaisPerto(lngLat, px = 14) {
  // Cola nos cantos de talhões já desenhados (divisa em comum, sem sobreposição) e no primeiro ponto (fechar).
  const alvo = map.project(lngLat);
  let melhor = null, dmin = px;
  const candidatos = [];
  for (const f of draw.getSnapshot()) if (f.geometry.type === "Polygon" && f.properties && f.properties.mode === "polygon") candidatos.push(...f.geometry.coordinates[0]);
  for (const c of candidatos) {
    const p = map.project(c), d = Math.hypot(p.x - alvo.x, p.y - alvo.y);
    if (d < dmin) { dmin = d; melhor = c; }
  }
  return melhor;
}

function cliqueContorno(e) {
  if (entregaModo) { entregaModo = false; marcarEntrega(e.lngLat.lat, e.lngLat.lng); return; }
  if (ferramenta !== "contornar") return;
  if (rascunho.length >= 3) {
    const p0 = map.project(rascunho[0]), pc = map.project(e.lngLat);
    if (Math.hypot(p0.x - pc.x, p0.y - pc.y) < 16) { fecharContorno(); return; }
  }
  const colado = pontoMaisPerto(e.lngLat);
  rascunho.push(colado ? [colado[0], colado[1]] : arred([e.lngLat.lng, e.lngLat.lat]));
  desenharRascunho();
}

function fecharContorno() {
  if (rascunho.length < 3) { dica("Faltam pontos: marque pelo menos 3 cantos."); return; }
  const g = poligono([...rascunho, rascunho[0]]);
  rascunho = [];
  desenharRascunho();
  novoTalhao(g);
}

function desfazerPonto() {
  if (!rascunho.length) return;
  rascunho.pop();
  desenharRascunho();
}

function pontoGps() {
  if (!navigator.geolocation) { aviso("Este aparelho não informa a localização."); return; }
  dica("Buscando sua posição…");
  navigator.geolocation.getCurrentPosition((p) => {
    const prec = Math.round(p.coords.accuracy);
    rascunho.push(arred([p.coords.longitude, p.coords.latitude]));
    map.easeTo({ center: [p.coords.longitude, p.coords.latitude], duration: 300 });
    desenharRascunho();
    dica(prec > 25 ? `Ponto marcado, mas o sinal está fraco (erro de cerca de ${prec} m). Vá para céu aberto ou ajuste depois no mapa.` : `Ponto marcado (erro de cerca de ${prec} m). Ande até o próximo canto e marque de novo.`);
  }, () => { dica("Não consegui sua posição. Toque nos cantos no mapa."); }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
}

// ------------------------------------------------------------------ ferramentas de desenho
const DICAS = {
  contornar: "Toque em cada canto da lavoura. Para fechar, use o botão Fechar talhão. Dá para colar nos cantos de outro talhão.",
  mao: "Arraste o dedo em volta da lavoura (no computador: clique, mova e clique de novo). Ao terminar, o contorno é fechado e alisado.",
  retangulo: "Arraste de um canto ao canto oposto (ou clique num canto e depois no outro). Depois ajuste os pontos, se precisar.",
  circulo: "Arraste do centro até a borda (ou clique no centro e depois na borda). Bom para pivô central.",
};

function setFerramenta(f) {
  if (ferramenta === "contornar" && f !== "contornar") { rascunho = []; desenharRascunho(); }
  ferramenta = f;
  entregaModo = false;
  document.querySelectorAll(".ferr-btn[data-ferr]").forEach((b) => b.classList.toggle("ativo", b.dataset.ferr === f));
  $("acoesContorno").classList.toggle("escondido", f !== "contornar");
  if (f) { fecharForm(); $("acoesEdicao").classList.add("escondido"); }
  if (!draw) return;
  if (f === "mao") draw.setMode("freehand");
  else if (f === "retangulo") draw.setMode("rectangle");
  else if (f === "circulo") draw.setMode("circle");
  else draw.setMode(f ? "static" : (atual ? "select" : "static"));
  map.getCanvas().style.cursor = f ? "crosshair" : "";
  if (f) { dica(DICAS[f]); if (f === "contornar") desenharRascunho(); } else dica("");
}

function novoTalhao(geometria, nome) {
  // Todo desenho vira um polígono comum do Terra Draw, para o ajuste (pontos, mover, girar, ampliar) ser igual para todos.
  let g = geometria;
  if (nPontos(g) > MAX_PONTOS) g = simplificar(g);
  g = poligono(g.coordinates[0].map(arred));
  const [r] = draw.addFeatures([{ type: "Feature", properties: { mode: "polygon" }, geometry: g }]);
  if (!r || !r.valid) { aviso("Não consegui criar esse desenho" + (r && r.reason ? ` (${r.reason})` : "") + ". Tente de novo."); setFerramenta(null); return null; }
  porFeature.set(r.id, null);
  if (nome) sugeridos.set(r.id, nome.slice(0, 60));
  setFerramenta(null);
  selecionar(r.id);
  return r.id;
}

function selecionar(id) {
  draw.setMode("select");
  draw.selectFeature(id);
  mostrarForm(id);
}

// ------------------------------------------------------------------ formulário, lista e ajuste
function mostrarForm(featureId) {
  if (atual !== featureId) historico.delete(featureId);
  atual = featureId;
  const g = geomDe(featureId);
  ultima.set(featureId, g);
  const sid = porFeature.get(featureId);
  const t = talhoes.find((x) => x.id === sid);
  $("form").classList.remove("escondido");
  $("formTitulo").textContent = sid ? "Editar talhão" : "Novo talhão";
  $("btnSalvar").textContent = sid ? "Salvar alterações" : "Salvar talhão";
  $("btnExcluir").classList.toggle("escondido", !sid);
  $("nome").value = t ? t.name : (sugeridos.get(featureId) || `Talhão ${talhoes.length + 1}`);
  $("cultura").value = t && t.crop ? t.crop : "";
  $("plantio").value = t && t.planting_date ? t.planting_date : "";
  limparErro($("erroForm"));
  atualizarArea(g);
  $("acoesEdicao").classList.remove("escondido");
  dica("Arraste os pontos para ajustar. Toque no ponto do meio de uma linha para criar mais um. Arraste o talhão para mover. Use os botões para girar ou mudar o tamanho.");
  renderLista();
}

function atualizarArea(g) {
  if (!g) { $("area").textContent = ""; return; }
  const { ha, erros } = validarLocal(g);
  const per = turf.length({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: g.coordinates[0] } }, { units: "meters" });
  $("area").textContent = `Área: ${fmtHa(ha)} · perímetro ${Math.round(per).toLocaleString("pt-BR")} m · ${nPontos(g)} pontos`;
  if (erros.length) { $("erroForm").textContent = erros.join(" "); $("erroForm").classList.remove("escondido"); }
  else limparErro($("erroForm"));
}

function fecharForm() {
  atual = null;
  $("form").classList.add("escondido");
  $("acoesEdicao").classList.add("escondido");
  renderLista();
}

function renderLista() {
  const ul = $("lista");
  ul.replaceChildren();
  for (const [fid, sid] of porFeature) {
    const t = talhoes.find((x) => x.id === sid);
    const nome = t ? t.name : `${sugeridos.get(fid) || "Novo talhão"} (não salvo)`;
    const sub = t ? `${fmtHa(t.area_ha)}${t.crop ? " · " + t.crop : ""}` : "Toque para dar nome e salvar.";
    const b = el("button", { class: "talhao-item" + (fid === atual ? " sel" : ""), type: "button" }, el("strong", { text: nome }), el("small", { text: sub }));
    b.addEventListener("click", () => { setFerramenta(null); selecionar(fid); const g = geomDe(fid); if (g) map.fitBounds(turf.bbox({ type: "Feature", properties: {}, geometry: g }), { padding: 80, maxZoom: 18, duration: 400 }); });
    ul.append(el("li", {}, b));
  }
  if (!porFeature.size) ul.append(el("li", { class: "suave", text: "Nenhum talhão ainda." }));
}

function trocarGeometria(id, g) {
  // Aplica uma geometria nova a um talhão em edição e guarda a anterior para o Desfazer.
  const antes = geomDe(id);
  if (antes) { const h = historico.get(id) || []; h.push(antes); if (h.length > 30) h.shift(); historico.set(id, h); }
  draw.updateFeatureGeometry(id, g);
  ultima.set(id, g);
  atualizarArea(g);
}

function ajustar(tipo) {
  if (!atual) return;
  const g = geomDe(atual);
  if (!g) return;
  const f = { type: "Feature", properties: {}, geometry: g };
  let novo;
  if (tipo === "girarE" || tipo === "girarD") novo = turf.transformRotate(f, tipo === "girarE" ? 5 : -5, { pivot: turf.centroid(f).geometry.coordinates }).geometry;
  else if (tipo === "menos" || tipo === "mais") novo = turf.transformScale(f, tipo === "menos" ? 0.95 : 1.05, { origin: "centroid" }).geometry;
  else if (tipo === "simplificar") {
    novo = simplificar(g, Math.max(8, Math.floor(nPontos(g) / 2)));
    if (nPontos(novo) >= nPontos(g)) { dica("Já está com poucos pontos."); return; }
  }
  if (novo) trocarGeometria(atual, poligono(novo.coordinates[0].map(arred)));
}

function desfazerAjuste() {
  const h = historico.get(atual);
  if (!atual || !h || !h.length) { dica("Nada para desfazer."); return; }
  const g = h.pop();
  draw.updateFeatureGeometry(atual, g);
  ultima.set(atual, g);
  atualizarArea(g);
}

async function carregarTalhoes(ajustar) {
  const r = await api("/plots");
  talhoes = r.talhoes;
  draw.clear();
  porFeature.clear();
  historico.clear();
  ultima.clear();
  sugeridos.clear();
  if (talhoes.length) {
    const res = draw.addFeatures(talhoes.map((t) => ({ type: "Feature", properties: { mode: "polygon" }, geometry: t.geometry })));
    res.forEach((x, i) => { if (x.valid) porFeature.set(x.id, talhoes[i].id); });
    if (ajustar) {
      const [a, b, c, d] = turf.bbox({ type: "FeatureCollection", features: talhoes.map((t) => ({ type: "Feature", properties: {}, geometry: t.geometry })) });
      map.fitBounds([[a, b], [c, d]], { padding: 60, maxZoom: 17, duration: 0 });
    }
  }
  setFerramenta(null);
  draw.setMode("static");
  fecharForm();
  dica(talhoes.length ? "" : "Escolha como desenhar na barra de cima: o jeito mais simples é Contornar.");
}

// ------------------------------------------------------------------ importar KML ou GeoJSON
function lerKml(texto) {
  const doc = new DOMParser().parseFromString(texto, "application/xml");
  if (doc.getElementsByTagName("parsererror").length) throw new Error("O arquivo KML está com defeito.");
  const out = [];
  for (const pm of doc.getElementsByTagName("Placemark")) {
    const nome = ((pm.getElementsByTagName("name")[0] || {}).textContent || "").trim();
    const ring = (txt) => txt.trim().split(/\s+/).map((s) => s.split(",").map(Number)).filter((p) => p.length >= 2 && p.every(Number.isFinite)).map((p) => [p[0], p[1]]);
    for (const poly of pm.getElementsByTagName("Polygon")) {
      const c = poly.getElementsByTagName("coordinates")[0];  // o primeiro é o contorno externo (buracos não são aceitos)
      if (c) out.push({ nome, anel: ring(c.textContent) });
    }
    for (const ln of pm.getElementsByTagName("LineString")) {   // caminho fechado desenhado no Google Earth
      const c = ln.getElementsByTagName("coordinates")[0];
      const a = c ? ring(c.textContent) : [];
      if (a.length >= 4 && a[0][0] === a[a.length - 1][0] && a[0][1] === a[a.length - 1][1]) out.push({ nome, anel: a });
    }
  }
  return out;
}

function lerGeoJson(texto) {
  const j = JSON.parse(texto), out = [];
  const visita = (g, nome) => {
    if (!g) return;
    if (g.type === "Polygon") out.push({ nome, anel: g.coordinates[0].map((p) => [p[0], p[1]]) });
    else if (g.type === "MultiPolygon") g.coordinates.forEach((pl) => out.push({ nome, anel: pl[0].map((p) => [p[0], p[1]]) }));
    else if (g.type === "GeometryCollection") g.geometries.forEach((x) => visita(x, nome));
  };
  const feats = j.type === "FeatureCollection" ? j.features : j.type === "Feature" ? [j] : [{ geometry: j, properties: {} }];
  for (const f of feats) { const p = f.properties || {}; visita(f.geometry, String(p.name || p.nome || p.Name || "")); }
  return out;
}

async function importar(arquivo) {
  limparErro($("erroGeral"));
  if (arquivo.size > 5 * 1024 * 1024) { aviso("Arquivo grande demais (máximo de 5 MB)."); return; }
  let itens;
  try {
    const texto = await arquivo.text();
    itens = texto.trimStart().startsWith("<") ? lerKml(texto) : lerGeoJson(texto);
  } catch (e) { aviso(e.message && e.message.startsWith("O arquivo") ? e.message : "Não consegui ler o arquivo. Use KML ou GeoJSON."); return; }
  itens = itens.filter((x) => x.anel.length >= 4);
  if (!itens.length) { aviso("Não achei nenhuma área fechada nesse arquivo."); return; }
  const folga = Math.max(0, cfg.limites.max_por_produtor - porFeature.size);
  const usados = itens.slice(0, folga);
  setFerramenta(null);
  let ultimoId = null, n = 0;
  for (const it of usados) {
    const anel = it.anel[0][0] === it.anel[it.anel.length - 1][0] && it.anel[0][1] === it.anel[it.anel.length - 1][1] ? it.anel : [...it.anel, it.anel[0]];
    const id = novoTalhao(poligono(anel), it.nome);
    if (id) { ultimoId = id; n++; }
  }
  if (n) {
    const todos = draw.getSnapshot().filter((f) => f.geometry.type === "Polygon" && f.properties && f.properties.mode === "polygon");
    const [a, b, c, d] = turf.bbox({ type: "FeatureCollection", features: todos });
    map.fitBounds([[a, b], [c, d]], { padding: 70, maxZoom: 18, duration: 500 });
    aviso(`Importei ${n} área(s)${itens.length > usados.length ? ` (o limite de talhões cortou ${itens.length - usados.length})` : ""}. Toque em cada uma na lista para dar nome e salvar.`, false);
  }
  void ultimoId;
}

// ------------------------------------------------------------------ Terra Draw
function iniciarDesenho() {
  const cor = { fillColor: "#1f6f43", fillOpacity: 0.3, outlineColor: "#14502f", outlineWidth: 3 };
  draw = new TD.TerraDraw({
    adapter: new ADP.TerraDrawMapLibreGLAdapter({ map, lib: maplibregl }),
    modes: [
      new TD.TerraDrawPolygonMode({ styles: cor }),  // só guarda os talhões; o contorno por toques é o do BALK
      // "click-move-or-drag": funciona arrastando o dedo (celular) ou clicando e movendo (computador)
      new TD.TerraDrawFreehandMode({ styles: cor, drawInteraction: "click-move-or-drag" }),
      new TD.TerraDrawRectangleMode({ styles: cor, drawInteraction: "click-move-or-drag" }),
      new TD.TerraDrawCircleMode({ styles: cor, drawInteraction: "click-move-or-drag" }),
      new TD.TerraDrawSelectMode({
        styles: { selectedPolygonColor: "#f2b705", selectedPolygonFillOpacity: 0.3, selectedPolygonOutlineColor: "#8a6100", selectedPolygonOutlineWidth: 3,
                  selectionPointColor: "#ffffff", selectionPointOutlineColor: "#8a6100", selectionPointWidth: 7, midPointColor: "#f2b705", midPointOutlineColor: "#8a6100", midPointWidth: 6 },
        flags: { polygon: { feature: { draggable: true, rotateable: false, scaleable: false,
                 coordinates: { midpoints: true, draggable: true, deletable: true } } } },
      }),
    ],
  });
  draw.start();
  draw.on("finish", (id, ctx) => {
    if (ctx.action === "draw" && ["freehand", "rectangle", "circle"].includes(ctx.mode)) {
      const g = geomDe(id);
      setTimeout(() => { draw.removeFeatures([id]); if (g) novoTalhao(g); }, 0);   // vira polígono comum, já alisado
    } else if (id === atual) {          // moveu o talhão ou um canto
      const antes = ultima.get(id), agora = geomDe(id);
      if (antes && agora && JSON.stringify(antes) !== JSON.stringify(agora)) {
        const h = historico.get(id) || []; h.push(antes); if (h.length > 30) h.shift(); historico.set(id, h);
        ultima.set(id, agora);
      }
      atualizarArea(agora);
    }
  });
  draw.on("select", (id) => { if (porFeature.has(id) && id !== atual) mostrarForm(id); });
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

// ------------------------------------------------------------------ busca, GPS, entrega, conclusão
async function buscar() {
  const q = $("busca").value.trim();
  const caixa = $("resultados");
  caixa.replaceChildren();
  if (q.length < 2) return;
  const m = q.replace(",", " ").match(/^\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$/);
  if (m) { map.flyTo({ center: [parseFloat(m[2]), parseFloat(m[1])], zoom: 16 }); return; }
  try {
    const r = await api("/geocode?q=" + encodeURIComponent(q));
    if (!r.resultados.length) { caixa.append(el("p", { class: "suave", text: "Não achei esse lugar. Tente o município ou lat, lon." })); return; }
    for (const x of r.resultados) {
      const b = el("button", { type: "button", text: x.nome + (x.regiao ? " — " + x.regiao : "") });
      b.addEventListener("click", () => { map.flyTo({ center: [x.lon, x.lat], zoom: 14 }); caixa.replaceChildren(); });
      caixa.append(b);
    }
  } catch (e) { mostrarErro($("erroGeral"), e); }
}

function gps() {
  if (!navigator.geolocation) { aviso("Este aparelho não informa a localização."); return; }
  navigator.geolocation.getCurrentPosition(
    (p) => map.flyTo({ center: [p.coords.longitude, p.coords.latitude], zoom: 16 }),
    () => aviso("Não consegui sua localização. Use a busca."),
    { enableHighAccuracy: true, timeout: 10000 });
}

function marcarEntrega(lat, lon) {
  entrega = { lat, lon };
  if (entregaMarker) entregaMarker.remove();
  entregaMarker = new maplibregl.Marker({ color: "#8a5a2b" }).setLngLat([lon, lat]).addTo(map);
  $("entregaTxt").textContent = `Ponto marcado: ${lat.toFixed(4)}, ${lon.toFixed(4)}`;
  dica("");
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
  if (["localhost", "127.0.0.1"].includes(location.hostname)) window.__balk = { map, draw, porFeature, novoTalhao, setFerramenta, importar, lerKml, lerGeoJson };  // só para teste local
  if (entrega) marcarEntrega(entrega.lat, entrega.lon);
  await carregarTalhoes(true);

  document.querySelectorAll(".ferr-btn[data-ferr]").forEach((b) => b.addEventListener("click", () => setFerramenta(ferramenta === b.dataset.ferr ? null : b.dataset.ferr)));
  $("arquivo").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) importar(f); });
  map.on("click", cliqueContorno);
  $("btnFechar").addEventListener("click", fecharContorno);
  $("btnDesfazerPonto").addEventListener("click", desfazerPonto);
  $("btnPontoGps").addEventListener("click", pontoGps);
  $("btnCancelarDesenho").addEventListener("click", () => setFerramenta(null));
  $("edDesfazer").addEventListener("click", desfazerAjuste);
  $("edGirarE").addEventListener("click", () => ajustar("girarE"));
  $("edGirarD").addEventListener("click", () => ajustar("girarD"));
  $("edMenos").addEventListener("click", () => ajustar("menos"));
  $("edMais").addEventListener("click", () => ajustar("mais"));
  $("edSimplificar").addEventListener("click", () => ajustar("simplificar"));
  $("form").addEventListener("submit", salvar);
  $("btnCancelar").addEventListener("click", cancelar);
  $("btnExcluir").addEventListener("click", excluir);
  $("btnBuscar").addEventListener("click", buscar);
  $("busca").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); buscar(); } });
  $("btnGps").addEventListener("click", gps);
  $("btnConcluir").addEventListener("click", concluir);
  $("btnEntrega").addEventListener("click", () => { setFerramenta(null); entregaModo = true; draw.setMode("static"); dica("Toque no mapa onde entrega a colheita."); });
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select, textarea")) return;
    if (e.key === "Escape") { if (ferramenta) setFerramenta(null); else if (atual && !porFeature.get(atual)) cancelar(); }
    if (e.key === "Backspace" && ferramenta === "contornar") { e.preventDefault(); desfazerPonto(); }
    if (e.key === "Enter" && ferramenta === "contornar") fecharContorno();
  });
}

iniciar().catch((e) => {
  console.error("mapa:", e);
  aviso("Não consegui abrir o mapa. Recarregue a página.");
});
