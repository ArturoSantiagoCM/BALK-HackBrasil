# BALK

Orientação agronômica curta por **WhatsApp e SMS** para o pequeno produtor, sem app e sem hardware.
O produtor entra por WhatsApp, SMS ou CSV de uma cooperativa; o sistema recorta satélite, relevo, solo e clima do local,
roda a análise espacial e devolve nota de viabilidade (com mapa), orientação em frase simples e alertas de clima e logística.

**Problema em 3 linhas:** só 19,9% dos estabelecimentos rurais brasileiros recebem assistência técnica e cerca de 72% não têm
internet na propriedade (Censo Agropecuário 2017). O produtor decide plantio, pulverização e colheita sem dado do próprio terreno.
O BALK leva essa decisão ao canal que ele já usa, só quando há algo a decidir. Trilha: **Logística e automação** (módulo M7:
colheita, melhor hora de saída e previsão de recebimento da cooperativa).

> O sistema **orienta e não prescreve**: sem produto, sem dose. Todo relatório traz o aviso
> *"Estimativa orientativa a partir de dados de satélite e clima. Não substitui um engenheiro agrônomo."*

## Rodar em 5 comandos (Python 3.12)

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATA_MODE = "simulado"
uvicorn app.main:app --reload
```

Linux ou macOS: `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && DATA_MODE=simulado uvicorn app.main:app --reload`

Abra <http://localhost:8000> (o site), <http://localhost:8000/demo/index.html> (simulador, sem login) e <http://localhost:8000/docs> (API).
**Isto é o modo de desenvolvimento** (padrão sem `BALK_ENV`): liga o simulador, `/outbox` (mostra os códigos de verificação) e uma rota que apaga o banco. **Em servidor use sempre `BALK_ENV=production`.**
No simulador: **Importar CSV** (cooperativa fictícia, 5 produtores) → **Rodar alertas do dia** → responda **1** ou **2** no
celular de SMS → escolha um produtor e um destino em **Melhor hora de saída**. **Clique no link no fim de cada mensagem de WhatsApp**
para abrir o relatório detalhado (dados, mapas, a conta da nota e o porquê). Na demo ele avisa em vermelho que os dados são simulados.
Testes: `python -m pytest -q` (cerca de 11 minutos: gera as imagens dos relatórios; 3 testes são ignorados sem QGIS).
Imagem Docker padrão: Python enxuto (sem QGIS). QGIS e n8n são **opcionais** (`Dockerfile.qgis`, perfil `n8n` do compose); a rotina diária é `POST /jobs/daily` por cron.
Conferir as APIs externas: `python check_apis.py`.

Modos de dados (`DATA_MODE`): `simulado` (tudo fixo, funciona offline, é o da demo), `real` (Open-Meteo, Earth Search, OSRM)
e `auto` (tenta real, cai para cache e depois simulado). Copie `.env.example` para `.env` para chaves; nunca versione o `.env`.

## Arquitetura

O n8n orquestra, o FastAPI decide, o motor espacial calcula. Toda a lógica está no FastAPI (testável); o n8n só chama endpoints e envia mensagens.

```
WhatsApp / SMS / CSV ──> n8n (4 fluxos) ──> FastAPI ──> M1 cadastro · M2 dados do local · M3 motor espacial
                                                         M4 viabilidade · M5 alertas+silêncio · M6 mensagem · M7 logística
                                                         └─ SQLite · work/{id}/ (rasters) · rules.yaml · crops.yaml
```

| Pasta | Módulo |
|---|---|
| `app/ingest/` | M1: máquina de estados (INICIO → PEDE_LOCAL → PEDE_CULTURA → PEDE_PLANTIO → ATIVO), SMS único, CSV |
| `app/data/` | M2: clima (Open-Meteo), histórico de 5 anos, recortes Sentinel-2/DEM/SoilGrids, dados simulados |
| `app/geo/` | M3: **motor geo do BALK**: relevo (Horn, TPI), NDVI/NDMI/NDRE, zonas de manejo, área fraca, erosão, baixada x geada |
| `app/engine/` | M3: escolhe o motor (Python ou QGIS opcional, `qgis_engine.py` + `run_chain.py`) e desenha o mapa PNG de 6 painéis |
| `app/viability/` | M4: nota trapezoidal por fator, ranking de 3 culturas, fator limitante, orientação, confiança |
| `app/alerts/` | M5: pulverização (Delta T de Stull), geada, estresse (z-score do NDVI), colheita; silêncio |
| `app/message/` | M6: modelos fixos pt/es/en, SMS de até 160 caracteres sem acento, validador e IA de redação opcional |
| `app/logistics/` | M7: rota (OSRM), melhor hora de saída, frete estimado, previsão de recebimento da cooperativa |
| `n8n/` | WF1 entrada, WF2 diário, WF3 novo produtor, WF4 escoamento (gerados por `build_flows.py`) |
| `app/auth.py`, `app/site_api.py`, `app/db_site.py` | **O site**: cadastro com código pelo WhatsApp, sessão, talhões, safras e histórico (`/api/*`) |
| `web/` | Páginas do site (sem build): landing, cadastro, mapa para desenhar talhões (MapLibre + Terra Draw + Turf em `web/vendor/`), minha área, histórico |
| `demo/` | simulador web (`/demo/index.html`, só fora de produção), `coop.csv` (5 produtores sintéticos), `destinos.json` |

**Documentação:** [`docs/GUIA_PROGRAMADORES.md`](docs/GUIA_PROGRAMADORES.md) (como funciona cada parte, testar, adaptar, QGIS e licença) ·
[`docs/OPERACAO.md`](docs/OPERACAO.md) (**colocar para rodar de verdade**, com checklist) ·
[`docs/VALIDACAO_REGRAS.md`](docs/VALIDACAO_REGRAS.md) (o que a web confirmou de cada regra) ·
[`docs/BACKTEST.md`](docs/BACKTEST.md) (geada e chuva contra histórico real) ·
[`docs/COMPARACAO_SPEC_AMIGO.md`](docs/COMPARACAO_SPEC_AMIGO.md) (o que veio da SPEC de um colega e o que ficou de fora).

**Para uso real:** `BALK_ENV=production`, `BALK_API_KEY`, `PUBLIC_BASE_URL` https, webhooks da Meta e da Twilio. Confira com `python -m app.cli check`.

Contratos compartilhados em `app/models.py`. Limiares em `rules.yaml` e `crops.yaml`, com coluna de fonte.

## Fontes de dados

Sentinel-2 L2A e Copernicus DEM GLO-30 (Earth Search STAC, sem chave) · SoilGrids (ISRIC) · Open-Meteo (previsão, histórico, geocodificação) ·
OSRM (servidor de demonstração) · FAO EcoCrop e Embrapa como referência inicial dos limiares.

## Limites assumidos (dizer no pitch)

- **Não é tempo real de satélite.** O Sentinel-2 passa a cada poucos dias; o clima é horário. É análise sob demanda.
- **Regras iniciais vêm de referências públicas e estão em revisão** com agrônomos. Em 26/11/2026 foram **conferidas na web** (Embrapa, MAPA/ZARC, FAO, bulas da ADAPAR, ANTT):
  várias bateram, 11 faixas foram ajustadas e o que não achou fonte está marcado como **premissa** (`docs/VALIDACAO_REGRAS.md`; status também na página de relatório).
  Isso **não é validação por agrônomo**. Não dizer "validado".
- **Resolução de 10 m:** o círculo de 150 m tem ~7 ha; talhões pequenos têm margem de erro maior (reduzir a confiança).
- Cadastro só por município dá o centro da cidade, não a lavoura: só alertas de clima (sem NDVI nem viabilidade).
- Frete (R$ 6/km), velocidade (60 km/h), caminhão (30 t) e produtividade por cultura são **premissas** em `rules.yaml`/`crops.yaml`.
- Open-Meteo gratuito e OSRM público servem ao hackathon, não à venda. n8n é fair-code: reler os termos antes de oferecer como serviço.
- API interna protegida por **chave** (`BALK_API_KEY`) e webhooks por **assinatura**; em `BALK_ENV=production` o servidor recusa subir sem isso. LGPD: consentimento registrado, `SAIR` desativa, `python -m app.cli delete-producer` apaga tudo.
- Um processo e SQLite: para muitos produtores, trocar por Postgres e proxy com limite de requisições.

## Estado de cada parte (honesto)

| Parte | Estado |
|---|---|
| M1–M7, API, simulador, SMS, validador, silêncio | Implementados e cobertos por testes automáticos (`tests/`, mais de 250 testes, dados simulados) |
| **Relatório detalhado com link** (`app/report/`) | Cada mensagem de WhatsApp termina com um link para uma página com os dados coletados, mapas estilo SIG, a conta da nota e o porquê de cada alerta, com fonte e status de cada regra. Testado, inclusive no navegador |
| Governança de dados e entrega (`consent.yaml`, `app/delivery.py`, tabelas `consents`, `messages`, `contacts`, `plots`) | Consentimento versionado, opt-in de cooperativa em produção, sucessor somente leitura e histórico, log de mensagens com reserva por SMS, limite diário, exclusão completa (LGPD), talhões desenhados com validação de geometria. Testado |
| **Site** (`web/`, `app/auth.py`, `app/site_api.py`) | Cadastro com **código de 6 dígitos pelo WhatsApp** (aceites separados e versionados, código só como HMAC, 10 min, 5 tentativas, limites por telefone e IP, sessão opaca em cookie HttpOnly, link de uso único `MAPA`), **mapa para desenhar vários talhões** (validado no navegador e de novo no servidor), minha área (exportar, sair, apagar) e histórico por safra. Backend testado (`tests/test_site.py`); telas **conferidas no navegador com dados simulados** (cadastro, desenho, salvar, erro de sobreposição, concluir, relatório, histórico). **Não** testado: código por template real da Meta, mapa em celular real, edição de vértices por toque |
| **Vários talhões** (`service._analyze_unit`) | Uma análise, um relatório e uma mensagem **por talhão** (o nome só aparece com 2 ou mais); silêncio de 72 h por talhão, cota diária e semanal somando todos; talhões a menos de 5 km dividem o clima e a pulverização sai uma vez |
| **Histórico por safra** (`seasons`, `observations`) | Safra abre com cultura e data de plantio; cada cena de satélite vira uma observação (idempotente); o alerta de vigor compara com safras anteriores do mesmo talhão e cultura (confiança média) ou, sem histórico, com a série recente (baixa). Produtividade por `PRODUTIVIDADE 3,4` no WhatsApp ou na página de histórico |
| Backtest de geada e chuva (`app/backtest.py`) | **Executado** com histórico real do Open-Meteo (1.530 noites em 5 pontos): geada com 67% de precisão e 80% de recall contra reanálise, **não contra estação**; ponto fraco em Guarapuava (`docs/BACKTEST.md`) |
| Segurança (`app/security.py`, `app/webhooks.py`): chave de API, modo production, assinatura Meta e Twilio, idempotência, LGPD | Testado com cargas de exemplo; a assinatura da Twilio bate com o exemplo publicado por ela. **Não** exercitado contra as plataformas reais |
| Open-Meteo, geocodificação, OSRM (modo `real`) | Exercitados contra as APIs reais |
| Motor geo (`app/geo/`): relevo, índices, zonas, área fraca | Implementado e coberto por testes com valores conhecidos. As relações marcadas **[H]** (erosão, baixada x geada, umidade x clima) são hipóteses sem validação agronômica |
| Código do QGIS | **Não** está neste repositório (GPL; o regulamento proíbe fork). Os métodos publicados foram reimplementados; ver o guia, seção 6.6 |
| Sentinel-2 / DEM / SoilGrids reais, incl. SWIR, borda do vermelho (B8A) e pH (`app/data/sentinel.py`) | Lógica de recorte, escala/deslocamento e unidades **testada com STAC falso e arquivos locais** (`tests/test_dados_reais.py`). **Nunca baixou do Earth Search/SoilGrids de verdade** (o ambiente de desenvolvimento não alcançou o Earth Search) |
| Motor QGIS (`run_chain.py`), `Dockerfile`, `docker-compose.yml` | **Não testados** (sem Docker/QGIS). Confirmar IDs com `qgis_process list`/`help`; rodar `tests/test_equivalencia.py` |
| Fluxos do n8n | Gerados por script, **não importados** num n8n real; criar credenciais (inclusive "BALK API key") pela interface |
| WhatsApp Cloud API e Twilio (`app/channels.py`) | **Não testados** com contas reais; a demo usa o simulador. Passo a passo em `docs/OPERACAO.md` |
| IA de redação (`app/message/polish.py`) | Opcional; sem `ANTHROPIC_API_KEY` usa o texto fixo. Chamada real não testada |

## Desvios do guia (e por quê)

- Motores em `python_engine.py` / `qgis_engine.py` (não `python.py` / `qgis.py`) para não sombrear o módulo `qgis` ao rodar scripts soltos.
- O cron diário do WF2 roda às **06:05**: o guia pede 05:00, mas o horário quieto vai até 6h e cortaria todos os alertas (exceto geada).
- Campos opcionais acrescentados ao contrato: `Producer.location_precision/state/active` e `SpatialStats.ndvi_ref_mean/std`.
- Dado ausente (ex.: argila) sai da nota e baixa a confiança, em vez de virar nota zero.
- O alerta de pulverização sempre devolve 1 item (pulverizar, adiar ou evitar), para o produtor saber também quando *não* fazer.
- A previsão de recebimento da cooperativa usa a janela de colheita das próximas 72 h e a área do círculo de análise (7 ha por produtor, premissa).

## Licença

MIT. Dados de demonstração sintéticos; nenhum dado pessoal real.
