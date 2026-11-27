# Certificação de funcionamento do MVP (27/11/2026)

O que foi conferido, parte por parte, e como cada parte se liga às outras. "Testado" quer dizer que há teste automático em `tests/`.
"Conferido no navegador" quer dizer que o caminho foi percorrido clicando nas telas, com o servidor em modo de demonstração (dados simulados).
Nada aqui foi feito com contas reais de WhatsApp ou Twilio. Os dados reais de satélite, relevo, solo e clima foram rodados (seção 5).

## 1. O caminho do produtor, de ponta a ponta

```
cadastro (WhatsApp, SMS, CSV ou site) ──> talhão (ponto, município ou desenho no mapa)
   ──> análise por talhão (clima + satélite + relevo + solo) ──> nota de viabilidade e alertas
   ──> mensagem curta no canal certo (com link) ──> relatório detalhado para o técnico (página, JSON e CSV)
   ──> resposta do produtor (1 = vou fazer, 2 = agrônomo) ──> registro, pedido para a equipe e métricas
   ──> ciclo diário (silêncio por talhão) ──> histórico por safra ──> referência de vigor da próxima safra
```

| Ligação | Como foi certificada |
|---|---|
| Site ↔ WhatsApp: o código pedido no site chega no WhatsApp do mesmo número | Conferido no navegador (o simulador mostra o código chegando) e testado (`test_site.py`). O número digitado com DDD ganha o 55 (`db.typed_phone`) para bater com o que o WhatsApp manda |
| Site → análise → WhatsApp: ao concluir, um relatório por talhão chega no celular | Conferido no navegador (2 talhões, 2 relatórios com mapa) e testado |
| WhatsApp → `MAPA` → site: link de uso único abre o mapa já identificado | Conferido no navegador (prévia do link no celular) e testado (o GET não gasta o link; só o POST da pessoa) |
| Ciclo diário → celular: o aviso chega com o link e os botões 1 e 2 | Conferido no navegador e testado (`test_certificacao.py`) |
| Resposta 2 → equipe: o pedido cita o aviso e traz o link do relatório | Testado e conferido no painel do simulador; endpoint interno `GET /escalations` |
| Resposta 1 e 2 → métricas (alcance, avisos, taxa de resposta, falhas) | Testado; endpoint interno `GET /metricas` e painel do simulador |
| Análise → safra → próxima análise: cada cena vira observação, e o alerta de vigor usa as safras anteriores | Testado (`test_site.py`); o relatório mostra a referência usada |
| Mensagem curta → relatório: tudo o que saiu da mensagem (relevo, zonas, água, contas) está no relatório | Testado (`test_geo_integracao.py`, `test_relatorio.py`) e conferido no navegador |
| Relatório → análise externa: dados em JSON e clima em CSV, sem a localização exata | Testado (`test_relatorio.py`) |
| CSV da cooperativa → convite (opt-in) → relatórios → previsão de recebimento | Testado e conferido no navegador; o convite agora sai pelo mesmo caminho de entrega (repetição, reserva por SMS, template de convite) |
| n8n → BALK: entrada manda a resposta e os relatórios; o diário só chama `/jobs/daily` | Testado (`test_certificacao.py` valida os 4 fluxos); não importado num n8n real |

## 2. Cada parte

| Parte | O que foi conferido | Resultado |
|---|---|---|
| Conversa pelo WhatsApp (`ingest/conversation.py`) | SIM, local (pin, lat,lon, município), cultura, data, comandos 1, 2, MAPA, HISTORICO, SUCESSOR, PRODUTIVIDADE, SAIR | OK. Corrigido: o número do SUCESSOR digitado com DDD agora ganha o 55 |
| SMS (`handle_sms`) | Cadastro em uma mensagem, aceite, 1 e 2, SAIR, 160 caracteres sem acento | OK. Corrigido: depois do "cadastro ok" vinha uma segunda mensagem repetindo a mesma explicação |
| Site: cadastro (`auth.py`, `site_api.py`) | Dois aceites separados, código de 6 dígitos (HMAC, 10 min, 5 tentativas atômicas, limites), sessão, sair, exportar, apagar | OK |
| Site: mapa (`web/js/mapa.js`) | Camadas (satélite Esri, Sentinel-2 2025, relevo com curvas, ruas, nomes, sombreado), contornar por toques com Desfazer e Fechar, ponto pelo GPS, mão livre, retângulo, círculo (pivô), importar KML e GeoJSON, mover, girar, ampliar, simplificar, desfazer ajustes, salvar, editar, excluir, sobreposição recusada pelo servidor | Conferido no navegador. Corrigido: o satélite da Esri não tem zoom 18 em boa parte do interior (vinha a imagem "Map data not yet available"); limitado a 17 e ampliado a partir daí |
| Motor geo e viabilidade (`geo/`, `viability/`) | Índices, relevo, zonas, área fraca, erosão, baixada, nota trapezoidal | OK (testes com valores conhecidos) |
| Alertas e silêncio (`alerts/`) | Pulverização, geada, estresse (com histórico), colheita; 72 h por talhão, 2 por dia e por semana, horário quieto | OK |
| Mensagens (`message/templates.py`) | Curtas e ao ponto: aviso em 3 linhas (ação, dado, confiança + como responder); relatório em até 6 linhas (nota, melhor opção, um ponto de atenção, confiança, aviso) e o link. Números em português com vírgula | Refeito nesta rodada; testado nos 3 idiomas e no SMS |
| Relatório detalhado (`report/`) | Para o técnico: conclusões amarradas, estatísticas completas, mapas, a conta de cada nota, critérios de cada alerta, clima hora a hora com Delta T, clima mensal, histórico do talhão, método com fórmulas e parâmetros, download em JSON e CSV | Refeito nesta rodada; testado e conferido no navegador |
| Entrega (`delivery.py`, `channels.py`) | Registro de cada mensagem, repetição, reserva por SMS, template por finalidade (alerta, código, convite) | OK. O provedor de demonstração agora guarda canal, hora, finalidade e sequência, para o simulador mostrar cada mensagem no celular certo |
| Logística e cooperativa (`logistics/`) | Melhor hora de saída, frete, previsão de recebimento | OK. Acrescentado: a previsão mostra as lavouras prontas que esperam tempo seco, e usa a área dos talhões desenhados |
| Simulador (`demo/index.html`) | Celular com WhatsApp (balões, horário, confirmações, prévia do link, imagem, botões de resposta rápida, enviar localização) e celular simples com SMS; os dois recebem tudo o que o BALK envia; painel da operação, da equipe e da cooperativa | Refeito nesta rodada; conferido no navegador |
| Segurança | Auditoria anterior (`security-auditor`) aplicada; testes de segurança verdes | OK |

## 3. Como repetir a certificação

1. `python -m pytest -q` (cerca de 15 minutos; 3 testes ignorados sem QGIS).
2. `DATA_MODE=simulado uvicorn app.main:app` e abrir `/demo/index.html`.
3. No celular do WhatsApp: "Oi" → SIM → 📎 localização → soja → data. Chega o relatório com mapa e link.
4. "Rodar alertas do dia" (às 10h): o aviso chega no celular com os botões 1 e 2. Responda 2: o pedido aparece no painel da equipe com o link.
5. Abra o site (botão no topo), cadastre o mesmo número: o código aparece no celular. Desenhe dois talhões e conclua: chegam dois relatórios.
6. No celular simples: "BALK soja 20/10 Sorriso MT" → SIM.
7. "Importar CSV" e "Melhor hora de saída".
8. Abra um relatório (`/r/...`): confira conclusões, estatísticas, clima hora a hora, método e os downloads.

## 4. O que não foi certificado

- Envio e recebimento reais pela Meta e pela Twilio (contas, templates aprovados, webhooks assinados de verdade).
- Dados reais em outras regiões e épocas (o teste real foi um talhão, em Sorriso, em novembro).
- Docker, motor QGIS e os fluxos do n8n importados num n8n real.
- O mapa num celular de verdade (toque, GPS em campo) e a cobertura do satélite da Esri em todas as regiões.
- As regras agronômicas marcadas como premissa (precisam de agrônomo).

## 5. Rodada com dados reais (27/11/2026)

Talhão retangular de 39 ha perto de Sorriso (MT), soja plantada em 15/10, `DATA_MODE=real`, banco separado. As 5 fontes responderam
(`python check_apis.py`: Open-Meteo previsão, histórico e geocodificação, Earth Search e OSRM).

| | Resultado |
|---|---|
| Tempo | 63 a 79 s por talhão (download dos recortes, análise e imagens do relatório) |
| Cena | Sentinel-2B de 11/11/2026, 100% do talhão visível (a de 01/11 estava coberta de nuvem e foi descartada) |
| Vegetação | NDVI médio 0,71 (vermelho ~0,07, infravermelho ~0,37), NDMI 0,13, NDRE 0,52 |
| Relevo e solo | 392 m, declividade média 2,6%; argila 27,7% e pH 4,9 (SoilGrids) |
| Conclusão | Soja nota 81 (boa), limitada pelo pH ácido (típico do Cerrado): "vale uma análise de solo". Aviso de evitar pulverizar (chuva até 63% em 24 h) |
| Mapas | Mostram a lavoura de verdade: linhas de plantio, e uma faixa de mata num córrego, mais úmida, mais baixa e com bordas inclinadas, coerente nas quatro camadas |

**Falhas que só apareceram com dado real (corrigidas e com teste):**
1. O Earth Search já aplica o deslocamento de reflectância (`earthsearch:boa_offset_applied`) e o código aplicava de novo: vermelho negativo em 85% dos pixels e NDVI de 1,30. Corrigido (`sentinel.scale_offset`), e índice com reflectância negativa agora é descartado (`geo/indices.py`).
2. A cena era escolhida pela nuvem do recorte de 100 km, não do talhão: a escolhida estava 100% nublada sobre ele. Agora o BALK confere a máscara de nuvem sobre o talhão em até 6 cenas e fica com a mais nova limpa; se o talhão estiver quase todo coberto, vira "sem imagem adequada" (só clima), sem fingir análise.
3. A argila não vinha (o mapa do SoilGrids exige baixar um bloco de 6 MB e a leitura falhava). Agora há reserva pela consulta por ponto do SoilGrids (uso moderado, ~5 consultas por minuto).

Como repetir: `DATA_MODE=real` no `.env`, cadastrar um talhão pelo site e concluir, ou rodar a análise de um produtor com `POST /analyze/{id}?full=true`.
