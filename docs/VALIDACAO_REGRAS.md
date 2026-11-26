# Validação das regras agronômicas e operacionais (busca na web, 26/11/2026)

**O que é este documento.** Para cada regra do BALK, o que a literatura e as fontes oficiais encontradas dizem, se o valor bateu, o que foi
ajustado e o que continua sem fonte. A busca foi feita na web (Firecrawl) por pesquisa e leitura de trechos.

**O que ele NÃO é.** Não é validação por engenheiro agrônomo, e não substitui a revisão formal prevista no projeto. Várias fontes abaixo são
técnicas (Embrapa, MAPA, bulas registradas, artigos), mas algumas são secundárias (blogs e sites de notícia do setor) e estão marcadas.
O pitch continua sem poder dizer "validado": o que dá para dizer é "conferido em fontes públicas e com a rastreabilidade de cada número".

Onde cada faixa aparece no produto: `crops.yaml` (blocos `fontes` e `validacao`) e `rules.yaml` (blocos `fonte` e `validacao_regras`).
A página de relatório mostra o status ao lado de cada fator e de cada alerta.

Legenda de status: **confirmado** (a fonte bate com o valor) · **ajustado** (o valor mudou para bater com a fonte) · **parcial** (a fonte confirma
parte) · **premissa** (nada encontrado; hipótese da equipe) · **não confirmado** (procuramos e não achamos).

---

## 1. Alertas

### 1.1 Pulverização — **confirmado** (horário e chuva: premissa)
| Regra do BALK | Valor | O que as fontes dizem | Ação |
|---|---|---|---|
| Temperatura máxima | 30 °C | Bulas registradas na ADAPAR-PR (ex. Accent, Radiant, Lastrole): temperatura abaixo de 30 °C | mantido |
| Umidade relativa mínima | 55% | Mesmas bulas: acima de 55% (uma delas, 50%) | mantido (o mais conservador) |
| Vento | 3 a 10 km/h | Mesmas bulas: média de 3 a 10 km/h; evitar inversão térmica | mantido |
| Temperatura mínima | 10 °C | Embrapa (tecnologia de aplicação): mínima de 10 °C, ideal 20-30, máxima 35 | **novo**: `temp_min: 10` em `rules.yaml` e no código |
| Delta T | 2 a 8 | Guias de pulverização (Austrália e Brasil): faixa ideal de 2 a 8; entre 8 e 12 ainda pode dar certo | mantido (conservador) |
| Chance de chuva até 30%; horário 5h-19h | | não achamos limite oficial | premissa |

Fontes: ADAPAR `https://www.adapar.pr.gov.br/sites/adapar/files/documento/2026-02/_accent.pdf` (e outras bulas do mesmo órgão) ·
Embrapa `https://sistemasdeproducao.cnptia.embrapa.br/FontesHTML/Ameixa/AmeixaEuropeia/tecnologia.htm` ·
`https://sprayers101.com/delta-t/` · `https://maissoja.com.br/condicoes-ambientais-para-a-aplicaca/`.
Nota: a página da Embrapa usada é de uma cultura específica (ameixa); vale como referência geral de tecnologia de aplicação, não como regra por cultura.

### 1.2 Geada — **parcial**
| Regra | Valor | O que as fontes dizem | Ação |
|---|---|---|---|
| Limite de geada na previsão a 2 m | 3 °C | Estudos brasileiros (Semina/UEL 2018; Sentelhas 1995, SciELO) medem a diferença entre a mínima no abrigo e na relva em noites de geada: em média de **4,2 a 6,3 °C** nas regiões analisadas. Logo, 3 °C no abrigo corresponde a relva abaixo de zero: o limite é conservador | **confirmado** como conservador |
| Ar frio se acumula em baixadas | qualitativo | IAG-USP (aula de geadas): formam-se "lagos de ar frio" em depressões, pelo ar que desce as encostas | **confirmado** (qualitativo) |
| Ajuste de 1 °C por relevo | 1 °C | uma fonte portuguesa cita 1 a 3 °C de efeito do relevo na mínima (trecho sem contexto completo) | **premissa conservadora** (dentro do intervalo, abaixo do teto) |

Fontes: `https://agris.fao.org/search/en/providers/122436/records/67597eb3c7a957febdf90cea` ·
`https://www.scielo.br/j/brag/a/FFVWrQ5TsJPXbYGC4ytzCzN/?lang=pt` · `https://master.iag.usp.br/pr/ensino/sinotica/aula12/`.
Pendência: a diferença abrigo-relva varia muito com nebulosidade e vento; um agrônomo local deveria calibrar o ajuste e o limite por região.

### 1.3 Estresse da lavoura — **premissa**
z-score do NDVI e fração de área fraca são métodos estatísticos padrão; os cortes (z < -1,5; 25% da área; 1 desvio) são da equipe. Sem fonte.

### 1.4 Colheita — **não confirmado**
As fontes encontradas tratam da **umidade do grão** na colheita da soja (ideal de 13% a 15%; colher tarde aumenta a abertura de vagens e a perda), não de
um limite de chuva em 48 h. A regra "48 h com até 2 mm" continua como premissa. Pendência: perguntar a um agrônomo por cultura.
Fontes consultadas: Cocari/Detec, Embrapa Infoteca (perdas na colheita de soja) e artigos do setor.

---

## 2. Faixas por cultura (`crops.yaml`)

### 2.1 Soja
| Fator | Antes | Depois | Fonte | Status |
|---|---|---|---|---|
| Temperatura (ótimo) | 20-30 °C | 20-30 °C | Embrapa Soja: adapta-se melhor a 20-30 °C; ideal em torno de 30; semeadura com solo abaixo de 20 °C compromete; acima de 40 °C é adverso | **confirmado** |
| Chuva do ciclo | 450-800 mm | **450-700 mm** | FAO (1986, 2002), citada em artigo: 450 a 700 mm bem distribuídos para a produtividade máxima (fonte secundária: o artigo cita a FAO) | **ajustado** |
| pH | 5,5-6,8 | **5,5-6,5** | Embrapa: 5,5 a 6,5 é a faixa ideal para arroz, milho e soja | **ajustado** |
| Declividade | 0-8% ótimo, 30% limite | igual | Classes de relevo da Embrapa (plano 0-3, suave ondulado 3-8, ondulado 8-20, forte ondulado 20-45): o ótimo coincide com até "suave ondulado"; o corte por cultura é premissa | **parcial** |
| Argila, geadas no ciclo | | | nada encontrado | premissa |

### 2.2 Milho
| Fator | Antes | Depois | Fonte | Status |
|---|---|---|---|---|
| Temperatura | 18-27 °C | **24-30 °C** | artigo de agronomia: tolera oscilações entre 10 e 30 °C, ideal de 24 a 30 °C; FAO GAEZ: germinação a partir de 10 °C, idealmente acima de 15 | **ajustado** |
| Chuva do ciclo | 400-800 mm | **500-800 mm** | Manual de recomendações técnicas do milho (AGRAER-MS): 500 a 800 mm bem distribuídos (Doorenbos & Kassam) | **ajustado** |
| pH | 5,5-7,0 | **5,5-6,5** | Embrapa (idem soja) | **ajustado** |

### 2.3 Café arábica
| Fator | Antes | Depois | Fonte | Status |
|---|---|---|---|---|
| Temperatura | 18-23 °C | igual | CaféPoint (site do setor, **fonte secundária**): média de aptidão entre 18 e 23 °C; outro site cita 18-21 | **confirmado** (secundária) |
| Chuva anual | 1400-1800 mm | **1200-1800 mm** | Portaria SPA/MAPA 579/2021 (ZARC café arábica, ES): precipitação ótima de 1200 a 1800 mm/ano | **ajustado** (fonte oficial) |
| pH | 5,0-6,0 | **5,5-6,0** | Incaper (Guarçoni 2017): valores sugeridos nos manuais para café entre 5,8 e 6,0 | **ajustado** |

### 2.4 Feijão
| Fator | Antes | Depois | Fonte | Status |
|---|---|---|---|---|
| Temperatura | 18-25 °C, limite 32 | **18-24 °C, limite 30** | Embrapa Feijão (Ater+): média ótima entre 18 e 24 °C, ideal 21; acima de 30 e abaixo de 12 prejudica. Outra página da Embrapa cita 17-25 °C como a faixa da maior parte da produção | **ajustado** |
| Chuva do ciclo | 200-450 mm | igual | um blog do setor cita 300-400 mm (não oficial) | premissa |
| pH | 5,5-6,8 | igual | Embrapa trata por **saturação por bases** (65-70%) em vez de pH; faixa geral de 6,0-6,5 para a maioria das plantas | premissa (parcial) |

### 2.4 Hortaliça (folhosa genérica)
pH ajustado para 6,0-6,5 (Embrapa, circular: faixa ideal para a maioria das plantas cultivadas). Temperatura, chuva, declive, geadas: premissa. É uma cultura
genérica: o ideal é cadastrar cada hortaliça (alface, tomate etc.) com a sua própria faixa.

### 2.5 Declividade
Embrapa (classes de relevo): **confirmado** para as classes. O produto também mostra a classe de relevo na página de relatório.

---

## 3. Operação e dados

| Item | Achado | Ação |
|---|---|---|
| **Open-Meteo** | O plano gratuito é só para **uso não comercial**, até 10.000 chamadas/dia, dados sob CC BY 4.0 (exige atribuição). Uso comercial exige assinatura | atribuição no rodapé do relatório; alerta em `rules.yaml` e no README. **Antes de cobrar de alguém, assinar o plano comercial ou hospedar o próprio servidor** |
| **SoilGrids** | Licença CC BY 4.0 (política de dados do ISRIC) | atribuição no relatório |
| **Sentinel-2 / DEM Copernicus** | dados abertos com atribuição ao Copernicus | atribuição no relatório |
| **NDMI** | o índice padrão é (B8A − B11)/(B8A + B11) (script oficial do Sentinel Hub); nossa coleta usava B08 | **ajustado**: a coleta real agora baixa a banda `nir08` (B8A) para NDMI e NDRE. Os cortes de classe (0,1 e 0,3) seguem premissa |
| **Frete (ANTT)** | O piso mínimo é por tipo de carga e nº de eixos, no formato (km × custo de deslocamento) + custo de carga e descarga. A Res. ANTT 6.084/2026 (publicada em 20/07/2026, segundo a imprensa do setor) deu, por exemplo, 8,3346 R$/km + R$ 782,50 para granel sólido em 9 eixos. A tabela completa estava em imagens | R$ 6/km **continua premissa**; criado `frete_fixo_rs` e o pedido de preencher com a linha do caminhão em `https://calculadorafrete.antt.gov.br/` |
| **WhatsApp (Meta)** | Desde 1º/10/2026, mensagens de serviço depois das 1.000 gratuitas/mês por número e templates de utilidade passam a ser cobrados. Brasil: cerca de R$ 0,035 por mensagem de utilidade ou serviço e R$ 0,3217 de marketing, segundo fornecedores (fonte secundária; a Meta cita US$ 0,0068 para utilidade no Brasil) | conferir sempre na tabela oficial; manter os textos como utilidade |

---

## 4. O que ainda exige um agrônomo (lista objetiva)
1. Revisar **todas** as faixas de `crops.yaml` marcadas como `premissa` (argila, geadas no ciclo, chuva do feijão e da hortaliça).
2. Calibrar o **limite de geada e o ajuste de relevo** por região (a diferença entre abrigo e relva varia com nebulosidade e vento).
3. Definir a regra de **colheita** (limite de chuva e umidade do grão por cultura).
4. Definir os cortes de **NDMI** e de **erosão** por cultura e fase, ou trocar por anomalias contra o histórico da própria lavoura.
5. Cadastrar **uma faixa por hortaliça** em vez da genérica.
6. Fazer **backtest** com o histórico do Open-Meteo: quantas geadas e janelas de pulverização o sistema teria acertado.

## 5. Limites desta validação
- Foi busca em trechos públicos: nem todas as páginas foram lidas por inteiro, e algumas fontes de pesquisa são blogs do setor.
- Valores de "faixa ideal" de fontes diferentes nem sempre coincidem (ex.: feijão 17-25 contra 18-24 °C). Escolhemos a faixa mais conservadora e registramos.
- A restrição de que variáveis de template do WhatsApp não aceitam quebra de linha (usada no código de envio) **não foi conferida nesta busca**: confirme na documentação da Meta ao criar o template.
