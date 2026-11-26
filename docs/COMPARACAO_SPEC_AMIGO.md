# Comparação: a SPEC de um amigo (para o Devin) contra o BALK atual

Fonte comparada: `Prompt hackathon.md` (SPEC + tarefas T0 a T11), uma especificação **para outra pessoa programar** em
**Convex + React/TypeScript + MapLibre**, com o Gemini para redação. Não há código dele aqui: é um documento de requisitos.
O nosso é código que roda (Python/FastAPI/SQLite). Esta comparação pergunta: o que dele vale trazer, o que nosso já faz melhor e o que dá para tirar.

## 1. Resumo em 10 linhas

- **A SPEC dele é melhor em princípios e em governança de dados** (LGPD, consentimento por finalidade, papéis, "nunca trocar dado real por simulado",
  estado explícito de "sem imagem adequada", polígono de talhão, backtest). Trouxe tudo isso que cabe em Python, **já implementado e testado** (seção 3).
- **O nosso é melhor em profundidade técnica e entrega**: motor geo (relevo, índices, zonas, erosão, baixada x geada), relatório com mapas e a conta da nota,
  validação das regras com fontes, logística com rota real (o dele usa linha reta), SMS e CSV de cooperativa funcionando, simulador, 200+ testes.
- **Não adotei a troca de stack** (Convex + React + TypeScript): reescrever a 4 dias da entrega seria o maior risco do projeto. Ver seção 5.
- **A maior lacuna que a SPEC dele expõe no nosso**: não existe o **site** (cadastro com código de verificação e mapa para desenhar talhões). A API de talhões e a validação já existem (seção 3); a tela não.

## 2. Comparação, tópico a tópico

Legenda: **Adotado** = trazido e testado · **Já tínhamos** · **Nosso melhor** · **Futuro** = vale, mas não coube · **Não adotar** = decisão consciente.

| Tópico | SPEC dele | Nosso (antes) | Decisão |
|---|---|---|---|
| Princípio "uma mensagem, uma decisão, sem sigla, sem gráfico" | explícito | a mensagem tinha "NDVI", "z = -3" | **Adotado**: mensagens sem sigla nos 3 idiomas (teste varre todos os textos) e o validador reprova sigla na saída da IA. Termos técnicos ficam só no relatório detalhado |
| "O LLM só redige" + validação de saída + modelo de reserva | sim | sim (`polish.py`, validador, texto fixo) | **Já tínhamos** (+ sigla técnica no validador) |
| Nunca apresentar dado simulado/velho como atual | sim | `DATA_MODE=auto` caía para simulado em silêncio | **Adotado**: em produção `auto` vale como `real` (nunca simula); canal sem credencial levanta erro; satélite fora do ar ou cena velha demais vira **"sem imagem adequada"** (só clima, com aviso); cena com mais de 30 dias avisa |
| Falha externa não gera alerta | sim | análise podia quebrar o ciclo todo | **Adotado**: `run_daily` pula o produtor que falha e lista em `erros`; alerta não entregue não entra no silêncio |
| Consentimento: finalidade, versão do texto, data, origem, revogação | tabela `consents` | um booleano | **Adotado**: tabela `consents` + `consent.yaml` versionado (v0 provisório); `SAIR` revoga; exportação inclui |
| Número verificado antes de receber qualquer coisa | código por WhatsApp (no site) | consentimento por `SIM` na conversa (o número já é o remetente) | **Adotado em parte**: cooperativa/CSV agora exige **opt-in `SIM`** em produção (antes ficava ativo só pela declaração da cooperativa). O código no site só faz sentido com o site (Futuro) |
| Papéis: produtor e sucessor (sucessor só lê) | sim | só o produtor | **Adotado**: `SUCESSOR <número>`; o sucessor aceita por conta própria, recebe cópia dos alertas, só vê o histórico e não altera nada (testado) |
| Página de histórico somente leitura | sim | não existia | **Adotado**: `/h/<token>` (linha do tempo dos avisos, porquê, confiança, data, link ao relatório); `HISTORICO` na conversa |
| Registro de mensagens (id do provedor, estado) e reenvio controlado + queda para SMS | sim | não registrávamos nada | **Adotado**: tabela `messages`; 2 tentativas com recuo; **reserva por SMS**; status da Meta (enviada/entregue/lida/falhou) atualiza o registro |
| Limite diário por contato, intervalo mínimo, prioridade | sim | semanal e 72 h | **Adotado**: `max_por_dia` (geada é exceção) |
| Webhook: assinatura, idempotência, número associado a contato verificado | sim | sim | **Já tínhamos** (+ sucessor e opt-in na checagem do remetente; número normalizado) |
| Exportação e exclusão de dados (LGPD) | sim | parcial | **Adotado**: exclusão agora apaga todas as tabelas (mensagens, consentimentos, contatos, links, talhões) e guarda só um registro **sem dado pessoal** (hash do telefone); exportação inclui consentimentos |
| Talhão como polígono (MapLibre + Terra Draw + Turf) | sim | só ponto + círculo de ~7 ha | **Adotado no backend**: validação (fechado, sem autointerseção, no Brasil, área mínima e máxima, sem sobreposição, limites) com área geodésica conferida a 1% por cálculo independente; análise usa os pixels do talhão; `POST /plots`. **Falta a tela de desenho** (Futuro) |
| Cultura e plantio **por talhão** | sim | por produtor | **Adotado**: o talhão traz cultura e data; a análise usa as do talhão |
| Vários talhões com mensagem por talhão ("colheita do talhão 2") | sim | um local por produtor | **Futuro**: hoje analisa o **maior** talhão; os demais ainda não têm mensagem própria (documentado) |
| Backtest com histórico real (geada e chuva) | exigido | não existia | **Adotado e executado**: `python -m app.cli backtest`; resultado real em `docs/BACKTEST.md` (geada: 67% de precisão e 80% de recall em 1.530 noites; ponto fraco: Guarapuava) |
| Satélite: mediana, percentis, fração válida, cenas usadas | sim | média, desvio, máscara de nuvem | **Futuro** (acrescentar percentis e fração válida) |
| Histórico por talhão e safra (observations, seasons) para comparar com safras anteriores | sim | `analyses` em JSON | **Futuro**: tabela de observações por data de cena; hoje o alerta de vigor compara com a vizinhança (confiança baixa) |
| Idempotência de análise (só cria observação quando há cena nova) | sim | cache de 24 h do pacote | **Futuro** (parte já coberta pelo cache) |
| Clima: observado separado de previsto, com fonte e horizonte | sim | só previsão (e diz que é previsão) | **Futuro** |
| Parâmetros de regras por cultura, **estádio e região** em arquivo | sim | por cultura | **Futuro** (estádio e região) |
| Decisão com resultado `sem_dado` e motivo | sim | `None` | **Futuro** (útil para explicar "por que não avisei") |
| Assistente com function calling (consultas autorizadas) | sim, com Gemini | comandos fixos (SIM, SAIR, 1, 2, HISTORICO, SUCESSOR) | **Futuro**: vale muito para a demo; precisa de chave de LLM e de um desenho de funções com checagem de dono e papel |
| Site: início, cadastro com consentimento e código, mapa, "meus talhões" | sim | **não existe** | **Futuro (o maior)**; ver seção 4 |
| Sessão opaca com hash e link de uso único | sim | links por token para relatório e histórico (com expiração) | **Futuro** (só quando houver site) |
| Módulo de colheita e escoamento | clima na origem, destino e ponto médio em reta | rota OSRM, melhor hora de saída, frete, previsão da cooperativa | **Nosso melhor** |
| Relevo, NDMI/NDRE, zonas, erosão, baixada x geada | ausente | sim | **Nosso melhor** |
| Relatório detalhado com mapas, a conta da nota e a fonte de cada regra | ausente | sim | **Nosso melhor** |
| Validação das faixas com fontes (Embrapa, MAPA, bulas) | "a validar com agrônomo" | feita e registrada | **Nosso melhor** (não substitui o agrônomo) |
| SMS de reserva e CSV de cooperativa | "estrutura" / fora do MVP | funcionando | **Nosso melhor** |
| Dados ambientais reais na demo | exige; só identidade é sintética | demo usa dados **simulados** (rotulados) | **Mudar para a final**: usar dado real em cache nos 3 pontos de demo (ver seção 6) |
| Convex, TypeScript, pnpm, Playwright, WorkOS (opcional) | sim | Python | **Não adotar** (seção 5) |
| Gemini | sim | IA opcional via Anthropic | **Neutro**: a interface é um adaptador; troque se o júri preferir |
| Áudio, perecíveis, indicadores extras | secundários | fora | **Concordamos em deixar para depois** |

## 3. O que foi trazido para o código agora (tudo testado: 207 testes verdes)

| Ganho | Onde | Testes |
|---|---|---|
| Nunca simular em produção; canal sem credencial dá erro | `config.data_mode`, `channels.get_channel` | `test_spec_amigo.py` |
| "Sem imagem adequada", aviso de cena antiga, ciclo diário resiliente | `service.py`, `message/templates.py`, `rules.yaml` (`satelite`) | `test_spec_amigo.py` |
| Mensagens sem sigla | `message/templates.py`, `message/polish.py` (`ACRONYMS`) | varre os 3 idiomas |
| Consentimentos versionados, SAIR revoga, telefone normalizado | `consent.yaml`, `db.py`, `ingest/conversation.py` | `test_spec_amigo.py` |
| Opt-in de cooperativa/CSV em produção | `ingest/csv_import.py`, `config.csv_requires_optin` | `test_spec_amigo.py` |
| Registro de mensagens, repetição, reserva por SMS, status da Meta | `delivery.py`, `db.py`, `webhooks.py` | `test_spec_amigo.py`, `test_seguranca.py` |
| Sucessor (só leitura) e histórico `/h/<token>` | `ingest/conversation.py`, `main.py`, `report/page.py` | `test_spec_amigo.py` |
| Limite diário por contato | `alerts/silence.py`, `rules.yaml` | `test_spec_amigo.py` |
| Exclusão completa (LGPD) com registro mínimo sem dado pessoal | `db.delete_producer`, tabela `audit_log` | `test_spec_amigo.py` |
| Talhões: validação, área geodésica, análise do polígono, API | `plots.py`, `geo/raster.py`, `geo/pipeline.py`, `main.py` | `test_talhoes.py` (20) |
| Backtest real | `backtest.py`, `cli.py`, `docs/BACKTEST.md` | `test_backtest.py` |

## 4. O que a SPEC dele ainda mostra que falta

**Feito depois (26/11/2026), ver `docs/GUIA_PROGRAMADORES.md` seção 16:**
1. ~~O site~~ **feito**: cadastro com código pelo WhatsApp, sessão, mapa para desenhar talhões (MapLibre + Terra Draw + Turf, sem build), minha área e histórico.
   Conferido no navegador com dados simulados; falta testar com template real da Meta e em celular de verdade.
2. ~~Vários talhões com mensagem por talhão~~ **feito**.
4. ~~Histórico por talhão e safra em tabelas próprias~~ **feito** (`seasons`, `observations`; o alerta de vigor compara com safras anteriores).

**Ainda falta:**
3. **Assistente conversacional** com funções autorizadas (maior efeito na demo).
5. **Observado separado de previsto** nos dados de clima e **estádio/região** nas regras.

## 5. Por que não migrar para Convex + React + TypeScript

- **Prazo.** A entrega é 30/11. Reescrever o que já roda, com 200+ testes, em outra linguagem e outro banco seria refazer o trabalho sem ganhar nenhuma capacidade nova.
- **Onde o Python é melhor aqui:** raster, Sentinel-2, relevo e zonas (rasterio, numpy, shapely, pyproj, matplotlib). A SPEC dele também manda o satélite para **um serviço Python separado**:
  na prática, o coração técnico dele já seria Python.
- **O que o Convex daria:** banco em tempo real, crons e funções serverless sem operar servidor. É um ganho real de operação, mas não resolve nenhuma lacuna acima.
- **Se um dia valer a pena:** manter o motor Python como serviço (como ele mesmo propõe) e colocar Convex/React só na frente. Os contratos já separam isso (`/analyze`, `/plots`, `/ingest`).

## 6. O que tirei ou simplifiquei do atual

| Item | Mudança | Por quê |
|---|---|---|
| Imagem Docker com QGIS | O `Dockerfile` padrão agora é **Python enxuto**; o QGIS foi para `Dockerfile.qgis` (opcional) | O QGIS não é necessário para rodar o BALK, é pesado e nunca foi construído; o regulamento ainda desencoraja derivados |
| n8n | Saiu do padrão do `docker-compose`: vira o perfil opcional `n8n`. A orquestração diária é `POST /jobs/daily` por cron | A SPEC dele diz para não introduzir n8n sem necessidade, e os fluxos nunca foram importados num n8n real. **Atenção:** a trilha "Logística e automação" pode valorizar automação visível; se a equipe quiser mostrar o n8n no vídeo, ele continua disponível |
| Queda silenciosa para dado simulado | removida em produção | princípio da SPEC dele (e nosso agora) |
| Mensagens com NDVI/z | removidas dos textos do produtor | o público não lê sigla |

**Uma decisão sua:** a demo atual usa **dados ambientais simulados** (rotulados). A SPEC dele proíbe isso (só identidade e telefone podem ser sintéticos),
e é mais convincente para o júri. Recomendo, para a final, rodar os 3 pontos de demo com `DATA_MODE=real` em uma rede que alcance o Earth Search, guardar o resultado em cache
e usar o modo simulado **só nos testes**. Sem isso, o relatório continuará exibindo o aviso vermelho de simulação.

## 7. Riscos que a comparação revelou no nosso (já tratados ou anotados)

- **Corrigido:** cooperativa cadastrava e já enviava mensagens sem o aceite da pessoa (em produção agora é opt-in).
- **Corrigido:** em produção o sistema poderia, ao falhar uma fonte, mostrar dado simulado como se fosse da lavoura.
- **Anotado:** o convite de opt-in e os alertas diários no WhatsApp precisam de **templates aprovados** (um para convite/boas-vindas, outro para alerta): são exigência da Meta e levam tempo.
- **Anotado:** o texto de consentimento (`consent.yaml`, v0) é **provisório** e precisa de revisão jurídica antes de produtor real.
