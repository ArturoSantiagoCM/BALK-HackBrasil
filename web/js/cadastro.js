import { api, mostrarErro, limparErro } from "/app/js/api.js";

const $ = (id) => document.getElementById(id);
let telefone = "";

async function carregar() {
  try {
    const cfg = await api("/config");
    $("t1").textContent = cfg.consentimento.dados_localizacao;
    $("t2").textContent = cfg.consentimento.mensagens;
    $("versao").textContent = "Texto de consentimento " + cfg.consentimento.versao + (cfg.consentimento.status ? " (" + cfg.consentimento.status + ")" : "") + ".";
  } catch (e) {
    mostrarErro($("erro1"), e);
  }
}

$("f1").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  limparErro($("erro1"));
  if (!$("c1").checked || !$("c2").checked) {
    mostrarErro($("erro1"), { msgs: [] });
    $("erro1").textContent = "Marque os dois itens para continuar. Eles são separados de propósito: você escolhe cada um.";
    return;
  }
  telefone = $("tel").value.trim();
  $("enviar").disabled = true;
  try {
    const r = await api("/signup/start", { method: "POST", body: { name: $("nome").value.trim(), phone: telefone, consent_dados: true, consent_mensagens: true } });
    $("passo1").classList.add("escondido");
    $("passo2").classList.remove("escondido");
    if (!r.enviado) {
      mostrarErro($("erro2"), { msgs: [] });
      $("erro2").textContent = "Não consegui enviar o código agora. Volte e tente de novo em alguns minutos.";
    }
    $("cod").focus();
  } catch (e) {
    mostrarErro($("erro1"), e);
  } finally {
    $("enviar").disabled = false;
  }
});

$("f2").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  limparErro($("erro2"));
  try {
    const r = await api("/signup/verify", { method: "POST", body: { phone: telefone, code: $("cod").value.trim() } });
    location.href = r.estado === "ATIVO" ? "/app/meus.html" : "/app/mapa.html";
  } catch (e) {
    mostrarErro($("erro2"), e);
  }
});

$("voltar").addEventListener("click", () => {
  $("passo2").classList.add("escondido");
  $("passo1").classList.remove("escondido");
  $("cod").value = "";
});

carregar();
