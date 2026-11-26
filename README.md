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

## Rodar em 5 comandos (Windows PowerShell; Python 3.12)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATA_MODE = "simulado"
uvicorn app.main:app --reload
```

Abra <http://localhost:8000> (simulador, sem login) e <http://localhost:8000/docs> (API).
No simulador: **Importar CSV** (cooperativa fictícia, 5 produtores) → **Rodar alertas do dia** → responda **1** ou **2** no
celular de SMS → escolha um produtor e um destino em **Melhor hora de saída**. Testes: `python -m pytest -q`.
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
| `demo/` | simulador web, `coop.csv` (5 produtores sintéticos), `destinos.json` |

**Guia completo para programadores** (como funciona cada parte, testar, adaptar, QGIS e licença): [`docs/GUIA_PROGRAMADORES.md`](docs/GUIA_PROGRAMADORES.md).

Contratos compartilhados em `app/models.py`. Limiares em `rules.yaml` e `crops.yaml`, com coluna de fonte.

## Fontes de dados

Sentinel-2 L2A e Copernicus DEM GLO-30 (Earth Search STAC, sem chave) · SoilGrids (ISRIC) · Open-Meteo (previsão, histórico, geocodificação) ·
OSRM (servidor de demonstração) · FAO EcoCrop e Embrapa como referência inicial dos limiares.

## Limites assumidos (dizer no pitch)

- **Não é tempo real de satélite.** O Sentinel-2 passa a cada poucos dias; o clima é horário. É análise sob demanda.
- **Regras iniciais vêm de referências públicas e estão em revisão** com agrônomos. Os números de `crops.yaml` são pontos de partida
  aproximados inspirados no EcoCrop e **não foram conferidos linha a linha**; a faixa de declividade é premissa da equipe. Não dizer "validado".
- **Resolução de 10 m:** o círculo de 150 m tem ~7 ha; talhões pequenos têm margem de erro maior (reduzir a confiança).
- Cadastro só por município dá o centro da cidade, não a lavoura: só alertas de clima (sem NDVI nem viabilidade).
- Frete (R$ 6/km), velocidade (60 km/h), caminhão (30 t) e produtividade por cultura são **premissas** em `rules.yaml`/`crops.yaml`.
- Open-Meteo gratuito e OSRM público servem ao hackathon, não à venda. n8n é fair-code: reler os termos antes de oferecer como serviço.
- MVP **sem autenticação** na API (há telefones no banco): proteger antes de qualquer uso real. LGPD: consentimento registrado, `SAIR` desativa.

## Estado de cada parte (honesto)

| Parte | Estado |
|---|---|
| M1–M7, API, simulador, SMS, validador, silêncio | Implementados e cobertos por testes automáticos (`tests/`, dados simulados) |
| Open-Meteo, geocodificação, OSRM (modo `real`) | Exercitados contra as APIs reais |
| Motor geo (`app/geo/`): relevo, índices, zonas, área fraca | Implementado e coberto por testes com valores conhecidos. As relações marcadas **[H]** (erosão, baixada x geada, umidade x clima) são hipóteses sem validação agronômica |
| Código do QGIS | **Não** está neste repositório (GPL; o regulamento proíbe fork). Os métodos publicados foram reimplementados; ver o guia, seção 6.6 |
| Sentinel-2 / DEM / SoilGrids reais, incl. SWIR, borda do vermelho e pH (`app/data/sentinel.py`) | Escritos conforme a documentação, **não testados** (o ambiente de desenvolvimento não alcançou o Earth Search) |
| Motor QGIS (`run_chain.py`), `Dockerfile`, `docker-compose.yml` | **Não testados** (sem Docker/QGIS). Confirmar IDs com `qgis_process list`/`help`; rodar `tests/test_equivalencia.py` |
| Fluxos do n8n | Gerados por script, **não importados** num n8n real; criar credenciais pela interface |
| WhatsApp Cloud API e Twilio (`app/channels.py`) | **Não testados** com contas reais; a demo usa o simulador |
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
