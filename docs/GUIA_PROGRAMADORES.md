# BALK: guia para programadores

Como o sistema funciona, como rodar, como testar e como adaptar cada parte. Escrito para quem está começando e usa IA para programar.
Leia na ordem: seções 1 a 4 em meia hora; depois use as seções 5 a 8 como consulta.

---

## 1. O que o sistema faz (e o que não faz)

O produtor manda uma localização por WhatsApp (ou escreve `BALK soja 20/10 Sorriso MT` por SMS, ou a cooperativa sobe um CSV).
O BALK baixa os dados do lugar (satélite, relevo, solo, clima), calcula, e devolve:

- uma **nota de viabilidade (0 a 100)** para 3 culturas, com o fator que mais pesa e uma frase de orientação;
- **relações entre as camadas**: onde a lavoura está fraca, zonas de manejo, risco de erosão, baixadas que seguram geada, umidade da vegetação contra a chuva prevista;
- **4 alertas** (pulverização, geada, estresse, colheita), no máximo 2 por semana, e a **melhor hora de saída** da colheita.

**Não faz:** receita de produto ou dose (o sistema orienta, não prescreve); previsão em tempo real de satélite (o Sentinel-2 passa a cada poucos dias); nada é "validado por agrônomo". Todo limiar está em `rules.yaml`/`crops.yaml` com a fonte.

## 2. Rodar na sua máquina

Windows PowerShell, Python 3.12.

```powershell
cd <pasta-do-projeto>
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATA_MODE = "simulado"
uvicorn app.main:app --reload
```

Linux ou macOS: `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && DATA_MODE=simulado uvicorn app.main:app --reload`.

Abra `http://localhost:8000` (simulador) e `http://localhost:8000/docs` (todas as rotas, com botão "Try it out").

| Variável | Valores | Para quê |
|---|---|---|
| `DATA_MODE` | `simulado` / `real` / `auto` | `simulado`: tudo fixo, funciona offline (a demo). `real`: Open-Meteo, Earth Search, OSRM. `auto`: tenta real, cai para cache e depois simulado |
| `ENGINE` | `python` / `qgis` | motor espacial. `qgis` só funciona dentro da imagem do QGIS; fora dela cai sozinho para `python` |
| `BALK_DB`, `BALK_WORK` | caminhos | banco SQLite e pasta dos rasters (os testes usam pastas temporárias) |

Chaves e senhas só no `.env` (copie de `.env.example`). Nunca no Git, nunca em prompt de IA.

## 3. Mapa do repositório e caminho dos dados

```
app/
  models.py        contratos (sagrado: só muda com os 4 de acordo)
  config.py        lê rules.yaml / crops.yaml e as variáveis de ambiente
  db.py            SQLite: produtores, análises, log de alertas, cache
  ingest/          M1  cadastro: conversa, SMS, CSV
  data/            M2  clima, histórico, recortes Sentinel/DEM/SoilGrids, dados simulados
  geo/             M3  MOTOR GEO do BALK (relevo, índices, relações)   <- novo
  engine/          M3  escolhe o motor (python ou qgis) e desenha o mapa
  viability/       M4  nota por cultura, ranking, orientação
  alerts/          M5  4 alertas e silêncio
  message/         M6  textos pt/es/en, SMS de 160 caracteres, validador, IA opcional
  logistics/       M7  rota, melhor hora de saída, previsão da cooperativa
  report/          RELATÓRIO DETALHADO: dados, imagens estilo QGIS, a conta da nota e o porquê (link na mensagem)
  service.py       junta tudo para um produtor (analyze_producer)
  main.py          rotas finas do FastAPI (create_app: internas, públicas, demo)
  security.py      chave de API, limite de requisições, assinatura Meta e Twilio, máscara de telefone
  webhooks.py      entrada real do WhatsApp (Meta) e do SMS (Twilio)
  cli.py           operação: check, backup, purge-reports, export-producer, delete-producer (LGPD)
demo/              simulador web (index.html), coop.csv, destinos.json
n8n/               4 fluxos (JSON) + build_flows.py que os gera
tests/             um arquivo de teste por módulo
rules.yaml         limiares de alertas, silêncio, relevo, água, erosão, zonas, logística
crops.yaml         faixas por cultura (FAO EcoCrop, aproximadas, em revisão) e pesos
```

**O que acontece em uma análise** (`app/service.py`, função `analyze_producer`):

```
produtor ─> get_weather (72 h) ─────────────────────────────────────────────┐
         ─> get_climate_history (5 anos) ──> chuva mensal média ──┐         │
         ─> build_local_package ──> work/{id}/*.tif               │         │
                   └─> geo.pipeline.run ──> SpatialStats ◄────────┘         │
                          (índices, relevo, relações)                        │
         ─> rank_crops(stats, clima) ──> 3 culturas com nota                 │
         ─> evaluate(produtor, weather, stats) ──> alertas (já com silêncio) ◄┘
         ─> render(...) ──> texto final por canal (WhatsApp completo, SMS ≤160)
```

Quem envia a mensagem (n8n ou `run_daily`) depois registra o alerta em `/alerts/log`, e é isso que alimenta o silêncio.

## 4. Contratos (`app/models.py`)

Toda função recebe e devolve estes objetos. Cole o arquivo inteiro como contexto fixo em qualquer prompt de IA.

- `Producer`: telefone, canal, lat/lon, cultura, data de plantio, consentimento, idioma, origem, `location_precision` (`ponto` ou `municipio`), estado da conversa.
- `Weather`: 72 linhas por hora com `time, temp, rh, rain_prob, rain_mm, wind_kmh, et0`.
- `SpatialStats`: saída do motor espacial. Campos de sempre (NDVI, declividade, argila, elevação, área, data da cena) mais, **todos opcionais**, os do motor geo:

| Campo novo | Significado | Unidade / valores |
|---|---|---|
| `ph` | pH do solo (SoilGrids, 0-5 cm) | pH |
| `ndmi_mean`, `moisture_class` | umidade da vegetação | índice; `baixa`/`media`/`alta` (cortes em `rules.yaml`, bloco `agua`) |
| `ndre_mean` | clorofila relativa | índice |
| `aspect_deg`, `aspect_label` | para onde a encosta desce | graus de bússola (0 = norte); N, NE, E, SE, S, SO, O, NO |
| `tpi_min` | baixada mais funda da área | metros (negativo = baixada) |
| `roughness_mean` | rugosidade do terreno | metros |
| `frost_relief_offset_c` | **[H]** quanto mais frio o ponto baixo fica que a previsão | °C, ≤ 0 |
| `erosion_index`, `erosion_class` | **[H]** risco relativo de erosão | 0 a 1; `baixo`/`medio`/`alto` |
| `weak_area_pct`, `weak_area_dir` | parte da área bem abaixo da referência e onde está | %; N..NO ou `C` (espalhada) |
| `zones` | zonas de manejo | lista de dicts: `id`, `share_pct`, `area_ha`, `label`, médias por camada |

`[H]` = hipótese que depende da validação de um agrônomo. Dica: se um campo novo não existe (camada ausente), ele vem `None` e **nada quebra**; o relatório só omite a linha.

- `Viability`: cultura, nota, fatores (0 a 1), fator limitante, orientação, confiança.
- `Alert`: tipo, ação, janela, `evidence` (os números usados), confiança, por quê.

## 5. Módulo por módulo

Para cada um: onde está, o que faz, como testar, armadilhas.

### M1: cadastro (`app/ingest/`)
- `conversation.py`: máquina de estados `INICIO → PEDE_LOCAL → PEDE_CULTURA → PEDE_PLANTIO → ATIVO`. Só avança com `SIM` (LGPD). `SAIR` desativa a qualquer momento. SMS tem o estado extra `AGUARDA_SIM`.
- `parse_sms("BALK soja 20/10 Sorriso MT")` aceita erro de digitação (`difflib`) e devolve o campo que faltou.
- `csv_import.py`: valida linha a linha e devolve erros por linha. Reimportar atualiza (idempotente). A coluna `consentimento` é a declaração da cooperativa.
- Teste: `pytest tests/test_ingest.py`. Armadilha: cadastro só por município dá o centro da cidade, não a lavoura; por isso o motor espacial só roda com `location_precision="ponto"`.

### M2: dados do local (`app/data/`)
- `weather.py`: Open-Meteo, 72 h, cache de 1 h, uma nova tentativa, último valor salvo como reserva. Vento em **km/h** (pedido explicitamente) e horário no fuso do ponto.
- `climate.py`: histórico de 5 anos agregado **por mês** (temperatura média, chuva média e, novo, **dias de geada**). `season_stats`/`season_frost_days` somam os meses do ciclo da cultura.
- `sentinel.py`: recortes de ~1 km: `red`, `nir`, `scl`, **`swir16` (NDMI)**, **`rededge1` (NDRE)**, DEM Copernicus, argila e **pH** do SoilGrids. Reflectância = `DN * scale + offset` (lido dos metadados do item). SoilGrids vem em g/kg e pH×10: dividir por 10.
- `simulated.py`: dados fixos para a demo e para os testes. `make_synthetic_package` cria rasters sintéticos; `relief="ondulado"` (padrão) põe uma baixada e uma faixa fraca de vegetação; `relief="plano"` é um plano inclinado para testes com valor conhecido.
- **Status:** o código real de Sentinel/SoilGrids nunca rodou (o ambiente de desenvolvimento não alcançou o Earth Search). Teste em outra rede com `DATA_MODE=real` e `python check_apis.py`.

### M3: motor espacial (`app/geo/` e `app/engine/`)
Seção 6, abaixo, explica em detalhe. Resumo: `geo.pipeline.run(work_dir, lat, lon, rain_month_mm)` devolve `(SpatialStats, Products)`; `engine.analyze(producer)` escolhe o motor; `engine/mapa.py` desenha o PNG de 6 painéis.

### M4: viabilidade (`app/viability/`)
- Nota de cada fator pela função trapezoidal `fit(x, a, b, c, d)` (a = mínimo absoluto, b-c = ótimo, d = máximo absoluto), de 0 a 1.
- Fatores: temperatura média e chuva do ciclo, declividade, argila, **pH**, **dias de geada no ciclo**, regularidade do NDVI. Pesos em `crops.yaml`.
- Nota final = média ponderada × 100; se algum fator for 0, **teto de 40**. Dado ausente **sai da conta** e baixa a confiança (não vira zero).
- Confiança: cena com menos de 10 dias = alta, até 30 = média, sem cena = baixa; sem argila ou sem clima, cai um nível.
- Teste: `pytest tests/test_viability.py tests/test_geo_integracao.py`.

### M5: alertas e silêncio (`app/alerts/`)
- `calc.py`: funções puras (`delta_t` de Stull 2011, `gdd`, `zscore`, `confidence_from`).
- `rules.py`: pulverização (janela de 3 h em 72 h; sempre devolve 1 item: pulverizar, adiar ou evitar), geada, estresse, colheita.
- **Geada com relevo:** o limite compara `previsão + frost_relief_offset_c`. Em baixada o alerta dispara com a previsão do ponto até 1 °C acima do limite, e a mensagem mostra as duas temperaturas.
- **Estresse localizado:** além do z-score do NDVI, dispara se ≥ 25% da área está fraca, e diz o lado ("vale conferir o lado norte").
- `silence.py`: corta o mesmo tipo em 72 h, mais de 2 por semana, horário quieto (20h-6h), duplicados do dia. Geada é exceção à cota e ao horário.
- Teste: `pytest tests/test_alerts.py`.

### M6: mensagem (`app/message/`)
- `templates.py`: modelos fixos por tipo, modo e idioma. `render(item, canal, idioma)`. SMS: até 160 caracteres, sem acento (`to_sms`), termina com `Resp 1=ok 2=ajuda`.
- O relatório de WhatsApp ganhou linhas do motor geo (relevo e erosão, zonas, umidade x chuva, baixada). Cada linha só aparece se o dado existir. O SMS não ganha linhas.
- `polish.py`: IA de redação **opcional**. Sem `ANTHROPIC_API_KEY` usa o texto fixo. O **validador em código** (números só da entrada, tamanho, lista proibida, ação e janela presentes) reprova a saída da IA e volta ao texto fixo.
- Teste: `pytest tests/test_message.py`.

### M7: logística (`app/logistics/`)
Rota (OSRM público, só para demo), amostra a cada 20 km, soma a chuva na hora em que o caminhão passa, escolhe a saída com menos chuva, frete = km × R$/km (premissa). `forecast.py`: toneladas e caminhões por dia para a cooperativa. Teste: `pytest tests/test_logistics.py`.

### API e n8n
`app/main.py` só tem rotas finas. O n8n só chama as rotas e envia mensagens; **nenhuma regra de negócio fica no n8n**. Os JSON são gerados por `python n8n/build_flows.py` e **nunca foram importados num n8n real**: importe, crie as credenciais pela interface e confira os nós.

## 6. O motor geo em detalhe (`app/geo/`)

### 6.1 Entradas e a grade
Tudo é reamostrado para a **grade de 10 m do vermelho** (UTM, em metros). A SCL (20 m) usa vizinho mais próximo; reflectâncias e DEM usam bilinear; argila e pH (250 m) usam vizinho mais próximo e são lidos **no pixel do ponto**. A área de análise é um **círculo de 150 m** (~7 ha, ~700 pixels). Camadas opcionais ausentes só deixam campos vazios.

| Arquivo em `work/{id}/` | Camada | Obrigatório |
|---|---|---|
| `red.tif`, `nir.tif` | reflectância B04, B08 | sim |
| `scl.tif` | classificação de cena (nuvem, sombra) | não (sem ela não mascara) |
| `swir.tif`, `rededge.tif` | B11, B05 | não (sem elas: sem NDMI, NDRE) |
| `dem.tif` | Copernicus DEM, metros | não (sem ele: sem relevo, erosão, baixada) |
| `clay.tif`, `ph.tif` | SoilGrids, em % e em pH | não |
| `meta.json` | data da cena, origem | não |

### 6.2 Arquivos e funções

| Arquivo | O que faz |
|---|---|
| `raster.py` | `read_stack` lê e alinha todas as camadas; `circle_mask` desenha o círculo |
| `indices.py` | `ndvi`, `ndmi`, `ndre` (diferença normalizada) e `scene_mask` (SCL 4 e 5 = vegetação e solo nu) |
| `terrain.py` | `slope_aspect` (Horn), `tpi`, `roughness`, `cold_pool_index`, `compass` |
| `relations.py` | zonas de manejo, área fraca, erosão, deslocamento de geada, umidade, balanço hídrico |
| `pipeline.py` | `run`: orquestra tudo e monta `SpatialStats` + `Products` (arrays para mapa e depuração) |

### 6.3 Fórmulas e convenções

- **NDVI** = (NIR − Vermelho)/(NIR + Vermelho). **NDMI** = (NIR − SWIR1)/(NIR + SWIR1). **NDRE** = (NIR − BordaVermelho)/(NIR + BordaVermelho). Só pixels com SCL 4 ou 5.
- **Declividade e aspecto (Horn 1981):** janela 3×3, `dz/dx = ((z13+2·z23+z33) − (z11+2·z21+z31)) / (8·dx)` e análogo para y; declividade em **%** = `100·√(dz/dx² + dz/dy²)`. Aspecto em graus de bússola **para onde a encosta desce**. Bordas: extrapolação linear (plano inclinado continua exato). Vizinho sem dado vira o valor central. Terreno plano: aspecto `NaN`.
  - Atenção à unidade: o QGIS pode entregar declividade em **graus**; aqui é **%** (`slope_degrees` converte).
- **TPI (Weiss 2001):** cota − média dos vizinhos dentro de `relevo.janela_m` (150 m). Negativo = baixada. As bordas da imagem (uma janela) ficam `NaN`.
- **Rugosidade:** raiz da soma dos quadrados das diferenças aos 8 vizinhos válidos.

### 6.4 As relações entre camadas (o que o BALK tem de próprio)

| Relação | Como é feita | Parâmetros (`rules.yaml`) | Status |
|---|---|---|---|
| **Zonas de manejo** | k-means (numpy, determinístico) sobre NDVI, declividade, TPI e NDMI padronizados; zonas ordenadas do NDVI mais fraco ao mais forte | `zonas.k`, `zonas.min_pixels` | método padrão; k é escolha |
| **Área fraca e lado** | pixels com NDVI abaixo de (referência − 1 desvio); centro de massa em relação ao ponto vira N..NO | `estresse.area_fraca_*` | método padrão |
| **Baixada e geada** | `índice = clip(−TPI/2 m)` × (1 se declividade ≤ 8%, senão 0,5); deslocamento = −`ajuste_relevo_c` × percentil 90 | `geada.tpi_depressao_m`, `geada.ajuste_relevo_c` | **[H]** |
| **Erosão** | `S × (0,4·R + 0,4·C + 0,2·K)` cortado em 0..1: S declividade/ref., R chuva mensal/ref., C cobertura = 1 − NDVI, K solo pela argila | bloco `erosao` | **[H]** índice relativo, **não é perda de solo em t/ha** |
| **Umidade x clima** | NDMI classificado em baixa/média/alta; balanço = chuva − ET0 previstos em 72 h; "atenção" se umidade baixa e balanço ≤ −5 mm | bloco `agua` | **[H]** cortes a calibrar por cultura |
| **Geadas no ciclo** | dias com mínima ≤ `geada.tmin` no histórico, somados no ciclo da cultura, entram na nota | `crops.yaml` (`geadas_ciclo`) | premissa |

### 6.5 Limites assumidos
- Pixel de 10 m: talhão pequeno mistura vizinhos; o círculo de ~7 ha é maior que muitas lavouras (mostre a área e reduza a confiança).
- DEM de 30 m reamostrado a 10 m: o relevo fino não existe nos dados.
- Argila e pH de 250 m: 1 ou 2 pixels no círculo; é um ponto de partida, não um laudo.
- Todo `[H]` é hipótese. Não apresente como validado.

### 6.6 A relação com o QGIS (decisão e por quê)

O pedido era usar o código aberto do QGIS como base. Ele foi **estudado**, mas o código dele **não está neste repositório**:

1. **Licença.** O QGIS é GPL (v2 ou posterior, conforme os cabeçalhos dos arquivos e `qgis.org/license`). Copiar código dele para cá faria o projeto inteiro virar obra derivada sob GPL, em conflito com a licença MIT escolhida, e traz obrigações de código-fonte e de nome (um derivado não pode se apresentar como "QGIS", segundo as diretrizes de marca do QGIS).
2. **Regulamento do hackathon.** O projeto do evento anota que **fork do QGIS no repositório não é permitido** (usar o QGIS instalado como ferramenta é). Releia o regulamento oficial antes de decidir diferente.
3. **Custo.** O QGIS 4 migrou para Qt6 e parte dos plugins ainda não acompanhou; manter um derivado é caro e o produtor nunca vê o QGIS.

O que foi feito no lugar: **reimplementação independente dos métodos publicados** em Python (numpy + rasterio + pyproj, as mesmas bibliotecas livres de base), usando o QGIS como **especificação de comportamento**: janela 3×3 com tratamento de nodata, pixel de tamanho positivo, mínimo de 3 linhas, rugosidade somando só vizinhos válidos, borda tratada explicitamente. Resultado: mesmos conceitos, sem GPL, mais camadas e relações.

| Conceito do QGIS / GDAL | Função do BALK |
|---|---|
| `gdal:slope` (percentual), `qgsslopefilter` | `terrain.slope_aspect` |
| `gdal:aspect` | `terrain.slope_aspect` (segunda saída) |
| `qgsruggednessfilter` | `terrain.roughness` |
| `gdal:rastercalculator` (NDVI) | `indices.ndvi` e irmãs |
| `native:zonalstatisticsfb` | médias por máscara em `pipeline.run` |
| `native:buffer` do ponto | `raster.circle_mask` |
| (não existe pronto) | `relations.*` |

O **motor QGIS continua opcional** (`ENGINE=qgis`, `app/engine/run_chain.py`) e serve como **conferência**: `tests/test_equivalencia.py` compara NDVI e declividade entre os dois. Ele **ainda só devolve os campos antigos** (NDVI, declividade, argila, elevação, área); os campos novos do motor geo vêm `None` com `ENGINE=qgis`. O `run_chain.py` é um esqueleto **nunca executado**: confirme cada ID com `qgis_process list` e `qgis_process help <id>`. No vídeo, abra o QGIS manualmente com os mesmos rasters de `work/{id}/` para mostrar que os números batem.

Se a equipe preferir mesmo usar código do QGIS, o caminho seguro é: não colocar nada dele neste repositório, falar com o organizador, e tratar qualquer trecho copiado como GPL com aviso e fonte.

## 7. Como testar

```powershell
python -m pytest -q                 # tudo (cerca de 1,5 min; usa dados simulados e banco temporário)
python -m pytest -q tests/test_geo.py            # só o motor geo (segundos)
python -m pytest -q -k geada                     # só testes com "geada" no nome
python -m pytest -q -x --lf                      # para no primeiro erro / só os que falharam
python check_apis.py                             # as APIs externas estão no ar? (latência)
```

Resultado esperado hoje: 157 passam, 3 são ignorados (equivalência com QGIS, que só roda onde o QGIS existe). A suíte inteira leva cerca de 4 minutos (gera as imagens dos relatórios); para o dia a dia, rode só o arquivo que você mexeu.

**Como os testes são organizados**

| Arquivo | Cobre |
|---|---|
| `tests/test_geo.py` | relevo (planos com valor conhecido), índices, TPI, rugosidade, zonas, área fraca, erosão, pipeline |
| `tests/test_geo_integracao.py` | motor geo chegando em geada, estresse, nota (pH, geadas) e relatório |
| `tests/test_engine.py` | rasters sintéticos 10×10 com resposta conhecida; SCL de 20 m mascarando nuvem |
| `tests/test_viability.py`, `test_alerts.py`, `test_message.py`, `test_logistics.py`, `test_ingest.py` | um módulo cada |
| `tests/test_api.py` | ponta a ponta pela API (cadastro, CSV, alertas do dia, silêncio, SMS 1/2) |
| `tests/conftest.py` | banco e pasta `work` temporários por teste, `DATA_MODE=simulado`, `NOW` fixo (quinta 10h), `make_hours()` |

**Receita para um teste novo** (peça isto à IA, com `models.py` colado):

```python
def test_minha_funcao_caso_normal():
    entrada = ...            # dado pequeno, com resposta que você sabe de cabeça
    assert minha_funcao(entrada) == esperado

def test_minha_funcao_dado_ausente():
    assert minha_funcao(None) is None   # nunca deve quebrar
```
Regras: valor conhecido (plano de 10% dá 10%), borda (vazio, NaN, uma linha), unidade (graus × metros, % × fração, km/h × m/s). Nunca dependa de internet: use `conftest.py`.

**Checklist manual (5 minutos, antes de mostrar)**
1. `uvicorn app.main:app` e abrir `http://localhost:8000`.
2. **Importar CSV**: 5 relatórios; o de WhatsApp tem mapa de 6 painéis; o de SMS tem ≤ 160 caracteres.
3. **Rodar alertas do dia**: aparece a geada por SMS para o cooperado de Aparados da Serra. Rodar de novo: nada (silêncio).
4. No celular de SMS, responder `1` e `2`.
5. **Melhor hora de saída**: mostra dia, hora, chuva e frete.
6. **Reiniciar demo** limpa tudo.

**Testar com dados reais** (em uma rede que alcance o Earth Search): `$env:DATA_MODE="real"`, cadastre um ponto, confira `work/{id}/` (devem existir `red.tif`, `nir.tif`, `scl.tif`, `swir.tif`, `rededge.tif`, `dem.tif`) e compare a declividade e o NDVI com o QGIS aberto manualmente.

## 8. Como adaptar (receitas)

**Nova cultura.** Em `crops.yaml`, copie um bloco de `culturas:`, mude `ciclo_meses`, `ciclo_dias`, `mes_plantio_usual`, `produtividade_t_ha` e as faixas `{a, b, c, d}` de cada fator, **anotando a fonte**. Regra: `a ≤ b ≤ c ≤ d` (o carregamento falha com mensagem clara se estiver fora de ordem). Rode `pytest tests/test_viability.py`. Para o cadastro por SMS/WhatsApp reconhecer o nome, nada mais é preciso (a lista vem do YAML); para nome traduzido, acrescente em `message/templates.py`, dicionário `CROPS`.

**Novo fator na nota** (por exemplo, altitude). (1) Crie o valor em `SpatialStats` (campo opcional em `models.py`, com aviso aos 4). (2) Calcule-o em `geo/pipeline.py`. (3) Em `viability/__init__.py`, acrescente o nome em `FACTORS` e o valor em `values` dentro de `score_crop`. (4) Em `crops.yaml`, acrescente a faixa em cada cultura, o peso em `padrao.pesos` (a soma deve dar 1) e a frase em `orientacao_por_fator`. (5) Teste: fator ótimo = 100, fator fora = teto de 40, dado ausente = sai da conta.

**Mudar um limiar** (vento de pulverização, limite de geada, % de área fraca). Só em `rules.yaml`, e atualize a coluna `fonte`. Não deixe número solto no código.

**Novo alerta.** (1) `Alert.type` em `models.py` (acrescente o literal). (2) Função `evaluate_xxx` em `alerts/rules.py` que devolve `Alert` com `evidence` (números) e `confidence`. (3) Chame-a em `alerts/__init__.py`. (4) Prioridade em `silence.py` (`PRIORITY`). (5) Modelos pt/es/en em `message/templates.py`, dicionário `T`, chave `(tipo, modo)`, incluindo a versão de SMS. (6) Testes: dispara, não dispara, mensagem nos 3 idiomas, SMS ≤ 160 sem acento.

**Nova camada raster** (por exemplo, MapBiomas). (1) Baixe o recorte em `data/sentinel.py` (ou módulo novo) para `work/{id}/nome.tif`, na unidade final. (2) Acrescente a linha em `geo/raster.py`, dicionário `LAYERS` (arquivo, reamostragem, obrigatória ou não). (3) Use em `geo/pipeline.py` e guarde em campo novo opcional de `SpatialStats`. (4) Se for sintética para a demo, gere em `data/simulated.py`. (5) Teste com valor conhecido.

**Nova relação entre camadas.** Escreva uma função pura em `geo/relations.py` que recebe arrays (e a máscara `aoi`) e devolve números ou rótulos; parâmetros no `rules.yaml`; chame no `pipeline.run`; teste em `tests/test_geo.py` com arrays 5×5 feitos à mão. Marque `[H]` se depende de calibração agronômica.

**Mudar o tamanho da área de análise.** `RADIUS_M` em `geo/pipeline.py` (150 m = ~7 ha). Para talhões menores, reduza e baixe a confiança.

**Novo idioma.** Em `message/templates.py` acrescente a língua em todos os dicionários (`T`, `WEEKDAYS`, `CONF`, `LBL`, `CROPS`, `FACTOR`, `ORIENT`, `SHORT`, `DIRS`, `TERRAIN`, `LOGISTICS`, `TODAY_TOMORROW`) e em `DISCLAIMER` (`viability/__init__.py`); `Producer.lang` em `models.py`. O teste `test_todo_alerta_sai_em_whatsapp_e_sms_nos_3_idiomas` mostra o formato.

**Novo país.** Muda: calendário agrícola (`mes_plantio_usual`, `ciclo_*`), faixas em `crops.yaml` (precisam de agrônomo parceiro), idioma, limites de coordenadas em `ingest/conversation.py` (`LAT_RANGE`, `LON_RANGE`), geocodificação (`countryCode` em `data/geocode.py`). Não muda: Sentinel-2, DEM, SoilGrids, Open-Meteo.

**Novo canal** (Telegram, etc.). Em `app/channels.py`, crie uma classe com `send(phone, texto, media_url=None)` e registre em `get_channel`. O resto do sistema não sabe qual canal é.

**Trocar a fonte de clima.** Só `data/weather.py` (`get_weather`) e `data/climate.py` (`get_climate_history`) conhecem o Open-Meteo. Mantenha o contrato `Weather` (72 horas, os 6 campos) e o formato mensal do histórico.

**Ligar o motor QGIS.** Dentro da imagem `qgis/qgis` (`Dockerfile`), `ENGINE=qgis`. Confira os IDs com `qgis_process list`, rode `tests/test_equivalencia.py` e anote o resultado no README.

## 9. Como usar IA para programar neste repositório

Uma função por vez, com contrato e teste. Modelo de prompt:

```
Contexto: projeto BALK, Python 3.12, FastAPI, SQLite. [cole app/models.py inteiro]
Tarefa: implementar [função] em [arquivo]. Entrada: [tipos e exemplo]. Saída: [tipo e exemplo].
Regras: só estas bibliotecas: [lista]; funções pequenas; comentários em português; não invente nomes de parâmetros de API (se não souber, diga).
Depois escreva testes pytest com estes casos: [casos]. Explique em 5 linhas o que fez e o que não tem certeza.
```

Onde a IA erra (confira sempre): nomes de campos de APIs externas, unidades (graus × metros, m/s × km/h, fração × %), fuso horário da previsão, escala e deslocamento da reflectância do Sentinel-2, valores agronômicos (trate como ponto de partida e registre a fonte).

Agentes prontos em `.claude/agents/`: `python-pro`, `fastapi-pro`, `test-automator`, `debugger`, `data-scientist` (para calibrar relações com dados), `backend-security-coder`, `security-auditor` e `repo-publication-auditor` (rodar os dois últimos **antes de publicar**), `technical-writer` (README e guias).

## 10. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `ModuleNotFoundError: app` ao rodar um script | rodando de fora da pasta do projeto | `cd` para a pasta; use `python -m uvicorn` / `python -m pytest` |
| `red.tif precisa estar em um CRS projetado` | raster em graus | reprojete para UTM antes (o Sentinel já vem em UTM) |
| declividade 100× maior ou menor | misturou grau e % ou metro e grau | `terrain.slope_aspect` espera a grade em **metros** e dá **%** |
| NDVI estranho (negativo, > 1) | escala/offset do Sentinel não aplicado | `sentinel.py` aplica `DN*scale+offset`; confira `raster:bands` do item |
| `tpi_min`, zonas e baixada vazios | grade menor que 2× a janela do TPI (150 m) | use o recorte de 1 km; em teste, janela menor |
| nenhum alerta aparece na demo | horário quieto (20h-6h) ou silêncio de 72 h | `POST /simulate/daily?hora=10` ou **Reiniciar demo** |
| `/analyze` lento (> 60 s) | baixando dados reais | `DATA_MODE=simulado` ou pré-baixar os 3 pontos de demo |
| Earth Search não resolve DNS | rede/firewall | `python check_apis.py`; usar o cache dos 3 pontos de demo |
| `ENGINE=qgis` sem efeito | não está na imagem do QGIS | cai sozinho para Python (aviso no log) |

## 11. Glossário

**NDVI** vigor da vegetação · **NDMI** umidade da vegetação · **NDRE** clorofila relativa · **SCL** classificação de cena do Sentinel-2 (nuvem, sombra) · **DEM** modelo de elevação · **TPI** posição no relevo (negativo = baixada) · **Aspecto** direção para onde a encosta desce · **GDD** graus-dia · **Delta T** diferença entre temperatura e bulbo úmido (qualidade da pulverização) · **ET0** evapotranspiração de referência · **STAC** catálogo de imagens de satélite · **UTM** coordenadas em metros · **[H]** hipótese a validar com agrônomo · **Silêncio** regras que limitam a frequência dos alertas.

---

## 12. O relatório detalhado (o link que vem depois da mensagem)

Toda mensagem de WhatsApp (relatório e alertas) termina com `Detalhes, mapas e o porquê: https://.../r/<token>`. A página mostra, em ordem:
o que enviamos · **os dados coletados** (fonte, data, resolução, valor na sua área) · **mapas estilo SIG** (NDVI, NDMI, declividade com setas, posição no relevo, zonas, área fraca, erosão) ·
**a conta da nota** fator por fator (valor, faixa ideal, nota, peso, **fonte e status de cada faixa**) · **cada alerta** com os critérios da regra, o valor previsto e se atendeu ·
como as camadas se combinam · o esquema "como o BALK pensou" · limites · fontes e atribuições. Há botão para baixar tudo em **um arquivo** (`/r/<token>/baixar`).

**Como funciona**
```
analyze_producer ──> report.explain.build(...)  -> dict JSON (dados, culturas, alertas, clima, legendas)
                 ──> db.create_report(...)      -> token aleatório (secrets.token_urlsafe), validade REPORT_TTL_DAYS
                 ──> with_link(mensagem, link)  -> link no fim de cada mensagem (SMS: só com SMS_INCLUDE_LINK=1 e se couber)
GET /r/<token> ──> report.ensure_images (gera os PNGs se faltarem) ──> report.page.render_page(...)  -> HTML
```
- O primeiro relatório (cadastro) já gera as imagens; o alerta do dia só gera na primeira visita (economiza tempo no envio em lote).
- `report/explain.py` **não decide nada**: só mostra, com os números, o que `rules.yaml` e `crops.yaml` já decidiram (`explain_crop` é a mesma conta de `score_crop`; há teste garantindo que a conta mostrada bate com a nota enviada).
- `report/images.py` desenha as imagens com matplotlib (escala de 200 m, seta do norte, círculo da área, eixos em metros a partir do ponto, legenda com unidade e estatística da área). `mapa.png` é o resumo de 6 painéis que vai junto da mensagem no WhatsApp.
- `report/page.py` gera um HTML único, leve, sem JavaScript e sem recursos externos.

**Privacidade e segurança do link:** token de 22 caracteres aleatórios; mesmo 404 para "não existe" e "expirou"; limite de 60 requisições por minuto por IP; cabeçalhos `noindex`, `no-referrer`, `Content-Security-Policy`; a página **não mostra o telefone** e arredonda as coordenadas (~1 km); nomes de imagem validados por regex. Quem tem o link vê o relatório: trate-o como pessoal.

**Dados simulados são avisados:** se o clima, o histórico ou o pacote do satélite forem simulados, a página mostra um aviso vermelho e o diagrama também. Isso evita mostrar demonstração como se fosse a lavoura do produtor.

**Adaptar**
- *Nova seção na página:* acrescente o dado em `explain.build` (JSON) e o bloco HTML em `page.render_page`. Teste em `tests/test_relatorio.py`.
- *Nova imagem:* função em `images.py` + entrada em `render_all` + legenda em `explain.image_captions` (título, como ler, conclusão com números).
- *Outro idioma da página:* os textos estão em português em `explain.py` e `page.py`; extraia para dicionários por idioma como em `message/templates.py`.
- *Mudar a validade do link:* `REPORT_TTL_DAYS`. Apagar vencidos: `python -m app.cli purge-reports`.

## 13. Rodar de verdade (resumo; o passo a passo está em `docs/OPERACAO.md`)

| Quero | Faço |
|---|---|
| ver o que falta | `python -m app.cli check` |
| subir em produção | `BALK_ENV=production` + `BALK_API_KEY` + `PUBLIC_BASE_URL` (https). O servidor **recusa subir** com pendências e passa a esconder simulador e `/docs` |
| chamar rotas internas | header `X-API-Key: <chave>` (ou `Authorization: Bearer`) em `/conversation`, `/ingest/producers`, `/analyze/{id}`, `/alerts/log`, `/logistics/plan`, `/cooperative/{id}/forecast`, `/producers`, `/jobs/daily`, `/jobs/purge`, `DELETE /producers/{id}`, `/ready` |
| receber WhatsApp | webhook `https://dominio/webhooks/whatsapp` (verificação GET + POST assinado com `X-Hub-Signature-256`; idempotente pelo id da mensagem) |
| receber SMS | webhook `https://dominio/sms/inbound` (assinatura `X-Twilio-Signature`; resposta em TwiML) |
| enviar alertas do dia | `POST /jobs/daily` às 06:05 (cron ou n8n); no WhatsApp o envio proativo usa o **template** de `WHATSAPP_TEMPLATE_NAME` |
| apagar os dados de um produtor (LGPD) | `python -m app.cli delete-producer <telefone>` ou `DELETE /producers/{id}` |
| backup | `python -m app.cli backup arquivo.db` |

Testes de segurança: `tests/test_seguranca.py` (chave, modo production, assinaturas, idempotência, LGPD) e `tests/test_dados_reais.py` (caminho de dados reais sem internet).

## 15. Governança de dados, entrega e talhões (trazidos da comparação com a SPEC de um colega)

Detalhe e justificativa: `docs/COMPARACAO_SPEC_AMIGO.md`. Resumo de onde mexer:

| Assunto | Arquivos | Como testar / adaptar |
|---|---|---|
| **Consentimento** por finalidade, versão do texto, origem e revogação | `consent.yaml`, `db.py` (`consents`), `ingest/conversation.py` (`grant`) | Mudou o texto? Suba `versao` em `consent.yaml`. `tests/test_spec_amigo.py::test_aceite_grava_finalidades...` |
| **Opt-in** de cooperativa (CSV) em produção | `ingest/csv_import.py`, `config.csv_requires_optin` | `CSV_REQUIRES_OPTIN=1`. Convite enviado por `main.py` (`/ingest/producers`) |
| **Sucessor** (só leitura) | `ingest/conversation.py` (`_handle_contact`), `db.py` (`contacts`) | Produtor escreve `SUCESSOR 5565999990000`; a pessoa aceita sozinha. Para dar mais poder ao sucessor, mude só `_handle_contact` |
| **Histórico** `/h/<token>` | `main.py`, `report/page.py` (`render_history`), `db.py` (`links`) | `HISTORICO` na conversa gera o link |
| **Entrega** com registro, repetição e reserva por SMS | `delivery.py`, `db.py` (`messages`), `webhooks.py` | `deliver(...)` é o único caminho de envio do ciclo diário e do webhook; trocar a política de repetição é `RETRIES`/`BACKOFF_S` |
| **Telefone normalizado** | `db.norm_phone` | todo acesso por telefone passa por ele (`5565...` do WhatsApp e `+55 65 ...` do CSV viram o mesmo) |
| **Sem imagem adequada** / cena velha | `service.py`, `rules.yaml` (`satelite`), `message/templates.py` | `satelite.descartar_apos_dias` e `aviso_apos_dias` |
| **Limite diário** | `alerts/silence.py`, `rules.yaml` (`silencio.max_por_dia`) | |
| **Talhões desenhados** | `plots.py` (`check_plot_input`: a validação única das duas portas), `db.py` (`plots`), `geo/raster.py` (`polygon_mask`), `geo/pipeline.py` (`polygon=`), `main.py` (`POST /plots`), `site_api.py` (`/api/plots`) | Limites em `rules.yaml` (`talhoes`). Vários talhões: ver seção 16 |
| **Backtest** | `backtest.py`, `cli.py` | `python -m app.cli backtest docs/BACKTEST.md` (internet). Testes sem rede em `tests/test_backtest.py` |
| **Exclusão e exportação (LGPD)** | `db.delete_producer`, `cli.py` | a exclusão deixa só `audit_log` (hash do telefone, sem dado pessoal) |

**Armadilha conhecida:** `norm_phone` mantém só dígitos; telefone sem dígito vira `"+"` e colide. Valide telefones na entrada (o CSV já exige 8 dígitos).

## 16. O site, vários talhões e o histórico por safra

**Identidade = número de WhatsApp verificado.** Sem senha. Fluxo: `POST /api/signup/start` (nome, telefone e os **dois** aceites, marcados separadamente) →
código de 6 dígitos pelo WhatsApp (SMS se falhar) → `POST /api/signup/verify` → conta `AGUARDA_TALHAO`, consentimentos gravados com origem `site` e a versão do texto,
sessão aberta → o produtor desenha os talhões → `POST /api/finish` (ATIVO) → um relatório por talhão no WhatsApp.

| Peça | Arquivo | Notas |
|---|---|---|
| Código, sessão, anti-CSRF | `app/auth.py` | Código via `secrets`, guardado só como **HMAC** com `BALK_AUTH_SECRET`. 10 min, uso único, 5 tentativas, 3 por hora por telefone, 10 por hora por IP, 60 s entre pedidos. Sessão = token aleatório (guardado só como hash) em cookie `balk_session` HttpOnly + SameSite=Lax (+ Secure em https). Chamadas que alteram dados exigem `Origin` do mesmo site |
| Tabelas | `app/db_site.py`, `app/db.py` | `verifications`, `sessions`, `magic_links`, `farms`, `seasons`, `observations` |
| API | `app/site_api.py` (`/api/*`, `/m/{token}`) | Toda rota de conta confere o dono (`producer_id` da sessão). A geometria é validada no servidor mesmo que o navegador já tenha validado |
| Link do WhatsApp | `MAPA` na conversa → `/m/{token}` | Uso único, 30 min. **O GET só mostra uma página; quem gasta o link é o POST** (o robô de pré-visualização do WhatsApp faz GET e não pode gastá-lo) |
| Páginas | `web/` | Sem build. `web/vendor/`: MapLibre GL 6.19 (ESM), Terra Draw, Turf (licenças em `web/vendor/LICENSES.md`). CSP `script-src 'self'`; imagens do mapa só do provedor de `MAP_TILES_URL` |
| Fundo do mapa | `config.map_tiles()` | OSM por padrão (demo). Para escala, trocar por provedor com contrato (decisão humana, ver `OPERACAO.md`) |

**Vários talhões** (`service.py`): `analyze_producer` roda `_analyze_unit` para cada talhão (do maior ao menor). Cada um tem a sua pasta de dados `work/{id}-p{plot}`,
o seu relatório e as suas mensagens; o nome do talhão só entra no texto quando há 2 ou mais. O resultado mantém `stats`, `ranking` e `report_url` do **maior** talhão
(compatibilidade) e traz todos em `units`. Regras de silêncio: 72 h **por talhão** (`alert_log.plot_id`); cota diária e semanal **por contato**, somando os talhões
(`already` em `evaluate`); a pulverização, que só depende do clima, sai uma vez para talhões a menos de 5 km (`SAME_WEATHER_KM`); a geada é por talhão (o relevo muda a mínima).

**Safras e observações:** `ensure_season` abre a safra do talhão quando há cultura e data de plantio (trocar a cultura fecha a anterior); `save_observation` grava uma linha por
cena nova (`UNIQUE(produtor, talhão, data da cena, fonte)`); `observation_history` entrega a referência de NDVI ao alerta de estresse: safras anteriores do mesmo talhão e cultura na mesma
fase do ciclo (±15 dias, mínimo 3 pontos, confiança **média**) ou a série recente da safra atual (mínimo 4, confiança **baixa**). `PRODUTIVIDADE 3,4 [talhão]` no WhatsApp e
`POST /api/seasons/{id}/close` fecham a safra com a produtividade.

**Testar:** `python -m pytest tests/test_site.py -q`. No navegador: iniciar o servidor em dev e abrir `/app/cadastro.html`; o código aparece em `GET /outbox` (só fora de produção).
**Limite conhecido:** o desenho foi conferido por clique no navegador do desktop; a edição de vértices por toque em celular real não foi testada.

## 14. Validação das regras na web

`docs/VALIDACAO_REGRAS.md` lista, regra por regra, o que a literatura e as fontes oficiais dizem, o que foi **confirmado**, **ajustado** (e para quê) e o que segue **premissa**. Os mesmos status aparecem
em `crops.yaml` (blocos `fontes` e `validacao`), em `rules.yaml` (`validacao_regras`) e na página de relatório, ao lado de cada fator e alerta. **Não é validação por agrônomo.**

Para **acrescentar uma faixa nova com fonte:** edite `crops.yaml` (`fatores`), cadastre a fonte em `fontes:` (id, título, link), aponte-a em `validacao:` (status e id) e atualize o `docs/VALIDACAO_REGRAS.md`. O teste `test_crops_yaml_tem_ph_e_geadas_validos_em_todas_as_culturas` e o do relatório (`toda faixa mostra de onde vem`) quebram se faltar a fonte.
