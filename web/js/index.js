const S = [
  {
    id: "pulv",
    t: "Hora de pulverizar",
    d: "Evita desperdício de defensivo com vento forte.",
    h: "05:45",
    m: "Bom dia, Seu João! Hoje das 6h às 9h está bom para pulverizar. Depois das 10h vem vento forte, melhor evitar.",
    c: "alta",
    sms: "BALK: Bom dia Seu Joao! Hoje 6h-9h bom p/ pulverizar. Apos 10h vento forte, evite. Confianca alta. 1=Vou fazer 2=Agronomo",
    f: [
      ["Vento às 7h", "6 km/h", 0.4, 92, "Open-Meteo"],
      ["Umidade do ar", "68%", 0.25, 85, "Open-Meteo"],
      ["Temperatura", "22 °C", 0.2, 90, "Open-Meteo"],
      ["Chuva em 6 h", "0 mm", 0.15, 100, "Open-Meteo"],
    ],
    lim: "Vento depois das 10h",
    v: "regras-0.1 (em revisão)",
  },
  {
    id: "gea",
    t: "Alerta de geada",
    d: "Protege hortaliças sensíveis antes do frio da madrugada.",
    h: "17:30",
    m: "Atenção! Na madrugada de quinta a temperatura cai para 2 °C. Vale proteger as hortaliças novas hoje à noite.",
    c: "alta",
    sms: "BALK ALERTA: Madrugada de quinta faz 2 graus. Proteja as hortalicas novas hoje a noite. Confianca alta. 1=Vou fazer 2=Agronomo",
    f: [
      ["Mínima prevista", "2 °C", 0.5, 95, "Open-Meteo"],
      ["Altitude do talhão", "820 m", 0.2, 70, "Copernicus DEM"],
      ["Céu limpo", "sim", 0.2, 90, "Open-Meteo"],
      ["Vento calmo", "3 km/h", 0.1, 100, "Open-Meteo"],
    ],
    lim: "Mínima prevista",
    v: "regras-0.1 (em revisão)",
  },
  {
    id: "col",
    t: "Colheita e estrada",
    d: "Sincroniza a colheita e o transporte antes da chuva.",
    h: "06:10",
    m: "Chuva forte prevista para quarta. Se puder, adiante a colheita do talhão 2 e saia para entrega antes das 5h.",
    c: "média",
    sms: "BALK LOGISTICA: Chuva forte quarta. Adiante colheita do talhao 2 e saia p/ entrega antes das 5h. Confianca media. 1=Vou fazer 2=Agronomo",
    f: [
      ["Chuva prevista", "38 mm", 0.45, 88, "Open-Meteo"],
      ["Maturação (NDVI)", "0,72", 0.25, 75, "Sentinel-2"],
      ["Tempo de rota", "2 h 10", 0.2, 60, "OSRM"],
      ["Incerteza da previsão", "alta", 0.1, 40, "Open-Meteo"],
    ],
    lim: "Incerteza da previsão",
    v: "regras-0.1 (em revisão)",
  },
  {
    id: "lav",
    t: "Olho na lavoura",
    d: "O satélite detecta uma área mais fraca que em outras safras.",
    h: "08:15",
    m: "O satélite mostrou que o canto norte do talhão 2 está mais fraco que nas outras safras. Vale caminhar por lá esta semana.",
    c: "vale conferir",
    sms: "BALK LAVOURA: Satelite mostra canto norte do talhao 2 mais fraco que outras safras. Vale conferir esta semana. 1=Vou olhar 2=Agronomo",
    f: [
      ["NDVI do canto norte", "0,41", 0.5, 55, "Sentinel-2"],
      ["NDVI médio do talhão", "0,68", 0.25, 80, "Sentinel-2"],
      ["Chuva dos últimos 15 dias", "12 mm", 0.15, 50, "Open-Meteo"],
      ["Declividade", "9%", 0.1, 70, "Copernicus DEM"],
    ],
    lim: "NDVI do canto norte",
    v: "regras-0.1 (em revisão)",
  },
];

let cur = 0;
let sms = false;

const $ = function(i) {
    return document.getElementById(i);
  };

const scen = $("scen");

S.forEach(function(s, i) {
  const b = document.createElement("button");

  b.type = "button";
  b.innerHTML = "<b></b><span></span>";
  b.firstChild.textContent = s.t;
  b.lastChild.textContent = s.d;
  b.addEventListener("click", function() {
    cur = i;
    render();
  });
  scen.appendChild(b);
});

$("r1").addEventListener("click", function() {
  reply("1", "Anotado. Eu volto a avisar se algo mudar.");
});

$("r2").addEventListener("click", function() {
  reply(
    "2",
    "Certo. Um agrônomo vai entrar em contato. (Resposta simulada nesta demonstração.)",
  );
});

[["l-video"], ["l-repo"]].forEach(function(a) {
  $(a[0]).addEventListener("click", function(e) {
    if (this.getAttribute("href") === "#") e.preventDefault();
  });
});

$("chan").addEventListener("click", function() {
  sms = !sms;
  this.setAttribute("aria-pressed", sms);
  this.textContent = sms ? "Ver como WhatsApp" : "Ver como SMS (sem internet)";
  render();
});

$("why").addEventListener("click", function() {
  const t = $("trace");
  t.hidden = !t.hidden;
  this.setAttribute("aria-expanded", !t.hidden);
  this.textContent = t.hidden ? "Mostrar a conta" : "Ocultar a conta";
});

render();

function bubble(txt, me, small) {
  const d = document.createElement("div");
  d.className = "msg" + (me ? " me" : "");
  d.textContent = txt;
  if (small) {
    const e = document.createElement("small");

    e.textContent = small;
    d.appendChild(e);
  }
  return d;
}

function render() {
  const s = S[cur];

  Array.prototype.forEach.call(scen.children, function(b, i) {
    b.setAttribute("aria-pressed", i === cur);
  });

  const chat = $("chat");

  chat.innerHTML = "";
  chat.className = "chat" + (sms ? " sms" : "");

  $("ch").textContent = sms ? "BALK · SMS" : "BALK · WhatsApp";
  $("tm").textContent = s.h;

  if (sms) {
    chat.appendChild(bubble(s.sms, false, s.sms.length + " de 160 caracteres"));
  } else {
    chat.appendChild(
      bubble(
        s.m + " (Confiança: " + s.c + ")",
        false,
        s.h + " · Responda 1 se vai fazer ou 2 para falar com o agrônomo",
      ),
    );
  }

  const rows = $("rows");
  rows.innerHTML = "";

  let tot = 0;

  s.f.forEach(function(r) {
    const p = r[2] * r[3];
    tot += p;

    const tr = document.createElement("tr");

    [
      r[0],
      r[1],
      String(r[2]).replace(".", ","),
      p.toFixed(1).replace(".", ","),
      r[4],
    ].forEach(function(c) {
      const td = document.createElement("td");

      td.textContent = c;
      tr.appendChild(td);
    });
    rows.appendChild(tr);
  });

  $("tmeta").textContent =
    "Índice da janela: " +
    tot.toFixed(0) +
    " de 100 · Fator limitante: " +
    s.lim +
    " · Confiança: " +
    s.c +
    " · Versão das regras: " +
    s.v +
    ". Valores de exemplo.";
}

function reply(txt, ans) {
  const c = $("chat");
  c.appendChild(bubble(txt, true, "agora"));
  c.appendChild(bubble(ans, false));
}
