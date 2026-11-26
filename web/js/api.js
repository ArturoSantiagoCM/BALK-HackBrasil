// Chamadas à API do site. Mensagens de erro em português claro; a sessão vai no cookie (HttpOnly), nunca em JS.
export async function api(path, { method = "GET", body } = {}) {
  let resp;
  try {
    resp = await fetch("/api" + path, {
      method, credentials: "same-origin",
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError(0, ["Sem conexão. Verifique a internet e tente de novo."]);
  }
  let data = null;
  try { data = await resp.json(); } catch (e) { /* corpo vazio */ }
  if (!resp.ok) {
    const d = data && data.detail;
    let msgs;
    if (d && typeof d === "object" && Array.isArray(d.erros)) msgs = d.erros;
    else if (typeof d === "string") msgs = [d];
    else if (Array.isArray(d)) msgs = ["Confira os campos preenchidos."];
    else msgs = ["Algo deu errado. Tente de novo."];
    throw new ApiError(resp.status, msgs);
  }
  return data;
}

export class ApiError extends Error {
  constructor(status, msgs) { super(msgs.join(" ")); this.status = status; this.msgs = msgs; }
}

export function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const kid of kids) e.append(kid);
  return e;
}

export function mostrarErro(node, err) {
  node.textContent = err instanceof ApiError ? err.msgs.join(" ") : "Algo deu errado. Tente de novo.";
  node.classList.remove("escondido");
}
export function limparErro(node) { node.textContent = ""; node.classList.add("escondido"); }
export function fmtHa(x) { return (Math.round(x * 100) / 100).toLocaleString("pt-BR") + " ha"; }
export function fmtData(iso) { return iso ? iso.slice(0, 10).split("-").reverse().join("/") : ""; }
