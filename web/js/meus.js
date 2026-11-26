import { api, ApiError, el, mostrarErro, limparErro, fmtHa, fmtData } from "/app/js/api.js";

const $ = (id) => document.getElementById(id);
const ESTADOS = {
  ATIVO: "Você está recebendo os avisos.",
  AGUARDA_TALHAO: "Falta desenhar o seu talhão no mapa para começar.",
  SAIU: "Você parou de receber avisos. Faça o cadastro de novo para voltar.",
};

async function carregar() {
  let me, pl;
  try {
    me = await api("/me");
    pl = await api("/plots");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) { $("semSessao").classList.remove("escondido"); return; }
    mostrarErro($("erroGeral"), e);
    return;
  }
  $("conteudo").classList.remove("escondido");
  $("ola").textContent = me.name ? "Olá, " + me.name : "Olá";
  $("numero").textContent = "WhatsApp terminado em " + me.phone_final;
  $("estado").textContent = ESTADOS[me.state] || "";
  const tb = $("tabela");
  tb.replaceChildren();
  if (!pl.talhoes.length) tb.append(el("tr", {}, el("td", { colspan: "4", class: "suave", text: "Nenhum talhão ainda." })));
  for (const t of pl.talhoes) {
    tb.append(el("tr", {}, el("td", { text: t.name }), el("td", { text: fmtHa(t.area_ha) }), el("td", { text: t.crop || "—" }), el("td", { text: fmtData(t.planting_date) || "—" })));
  }
  const ul = $("contatos");
  ul.replaceChildren();
  for (const c of me.contacts) {
    const b = el("button", { class: "btn sec peq", type: "button", text: "Retirar" });
    b.addEventListener("click", async () => { try { await api("/contacts/" + encodeURIComponent(c.phone), { method: "DELETE" }); carregar(); } catch (e) { mostrarErro($("erroContato"), e); } });
    ul.append(el("li", { class: "barra" }, el("span", { text: `Número terminado em ${c.phone_final} · ${c.state === "ATIVO" ? "recebendo" : "aguardando o SIM"}` }), b));
  }
}

$("btnContato").addEventListener("click", async () => {
  limparErro($("erroContato"));
  try {
    const r = await api("/contacts", { method: "POST", body: { phone: $("telContato").value.trim() } });
    $("telContato").value = "";
    $("erroContato").textContent = r.mensagem;
    $("erroContato").classList.remove("escondido");
    $("erroContato").classList.replace("erro", "ok");
    carregar();
  } catch (e) { $("erroContato").classList.replace("ok", "erro"); mostrarErro($("erroContato"), e); }
});

$("btnSair").addEventListener("click", async () => {
  if (!confirm("Parar de receber os avisos do BALK?")) return;
  try { await api("/optout", { method: "POST", body: {} }); location.href = "/"; } catch (e) { mostrarErro($("erroConta"), e); }
});

$("btnExcluir").addEventListener("click", async () => {
  const r = prompt("Isso apaga a sua conta, os talhões, o histórico e as mensagens, e não tem volta.\nPara confirmar, escreva APAGAR:");
  if (r === null) return;
  if (r.trim().toUpperCase() !== "APAGAR") { $("erroConta").textContent = "Não apaguei: faltou escrever APAGAR."; $("erroConta").classList.remove("escondido"); return; }
  try { await api("/me", { method: "DELETE", body: { confirmar: true } }); location.href = "/"; } catch (e) { mostrarErro($("erroConta"), e); }
});

$("btnLogout").addEventListener("click", async () => {
  try { await api("/logout", { method: "POST", body: {} }); } finally { location.href = "/"; }
});

carregar();
