# BALK: colocar para rodar de verdade (guia de operação)

Este guia leva do repositório até produtores reais recebendo mensagens. Ele diz, passo a passo, o que fazer e **o que já foi
verificado e o que ainda não foi**. Não pule a seção 9 (checklist).

## 0. O que existe hoje

| Parte | Estado |
|---|---|
| Lógica (cadastro, dados, motor geo, nota, alertas, mensagens, relatório com link, logística) | testada com dados simulados e com arquivos locais no lugar das APIs (157 testes) |
| Open-Meteo, geocodificação, rotas OSRM | exercitadas contra as APIs reais |
| Sentinel-2, DEM e SoilGrids **reais** | lógica de recorte, escala e unidades testada com STAC falso e arquivos locais; **nunca baixou do Earth Search/SoilGrids de verdade** (o ambiente de desenvolvimento não alcançou o Earth Search) |
| Assinatura dos webhooks da Meta e da Twilio, chave de API, modo production | testados com cargas de exemplo (a assinatura da Twilio bate com o exemplo da documentação) |
| WhatsApp Cloud API, SMS Twilio, IA de redação | **nunca falaram com os serviços reais** (sem contas) |
| Docker, QGIS, n8n | **nunca executados** (sem Docker nesta máquina) |

## 1. O que você precisa providenciar (ninguém faz isso por você)
1. **Um servidor** (Linux, 1 vCPU e 2 GB bastam para começar) com um **nome de domínio e HTTPS** (Caddy, nginx ou o balanceador do provedor). O link do relatório e os webhooks exigem HTTPS público.
2. **Conta na Meta (WhatsApp Business Platform)**: app, número de telefone verificado e **template de utilidade aprovado** (item 5). A aprovação pode levar de horas a dias.
3. **Conta Twilio** (ou outro provedor de SMS) e remetente aceito no Brasil. Confirme preços e regras de cadastro de remetente antes (contas de teste só enviam para números verificados).
4. Um **agrônomo** para revisar `crops.yaml` e `rules.yaml` (`docs/VALIDACAO_REGRAS.md`, seção 4).
5. **Plano comercial do Open-Meteo** (ou servidor próprio) assim que houver cobrança: o plano gratuito é só para uso não comercial.

## 2. Instalar e configurar
```bash
git clone <seu-repositório> balk && cd balk
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock.txt
cp .env.example .env     # preencha (seção 3)
python -m app.cli check  # lista o que falta
```
Em Docker: `docker compose up --build` (a imagem sobe em `BALK_ENV=production` e **recusa subir** com pendências).

## 3. As variáveis que importam (`.env`)
| Variável | Para quê |
|---|---|
| `BALK_ENV=production` | desliga simulador e `/docs`; exige chave e HTTPS |
| `BALK_API_KEY` | 24+ caracteres aleatórios. Gere: `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `BALK_AUTH_SECRET` | 24+ caracteres aleatórios, **diferente** da chave de API. Protege os códigos de verificação do site. Sem ele o servidor recusa subir. Trocar o valor invalida os códigos abertos (valem 10 min) e não afeta as sessões |
| `PUBLIC_BASE_URL` | `https://seu-dominio`: de onde saem os links do relatório e do mapa e a URL assinada da Twilio. Com https, o cookie da sessão sai `Secure` |
| `MAP_TILES_URL`, `MAP_TILES_ATTRIBUTION` | fundo do mapa do site (seção 5-B) |
| `DATA_MODE=auto` (ou `real`) | `auto`: tenta real, cai para cache e depois simulado. **Em `real` a falha de uma fonte vira erro**, em `auto` ela vira dado simulado com aviso no relatório |
| `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_TEMPLATE_NAME` | WhatsApp (seção 5) |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM` | SMS (seção 6) |
| `REPORT_TTL_DAYS` | validade do link do relatório (padrão 30) |
| `ANTHROPIC_API_KEY` | opcional: reescrita das mensagens (o validador em código reprova número inventado) |

## 4. Primeira execução com dados reais (faça antes de ligar canais)
1. `python check_apis.py`: as 5 fontes devem dizer OK. Se o **Earth Search** falhar (como falhou no desenvolvimento), resolva rede/DNS antes de seguir.
2. `DATA_MODE=real python -m uvicorn app.main:app` em uma máquina de teste e cadastre um ponto de uma lavoura conhecida (`POST /conversation` com a chave).
3. Confira em `work/<id>/`: `red.tif`, `nir.tif`, `scl.tif`, `swir.tif`, `rededge.tif`, `nir08.tif`, `dem.tif`, `meta.json` com `"source": "earth-search"`. Se faltar `clay.tif`/`ph.tif`, o SoilGrids não respondeu (o sistema segue sem esses fatores e baixa a confiança).
4. Abra o relatório (o link vem na mensagem): **não deve haver** o aviso vermelho "dados SIMULADOS".
5. Compare com o QGIS aberto manualmente com os mesmos rasters: declividade e NDVI devem bater (`tests/test_equivalencia.py` automatiza isso onde há QGIS).
6. Guarde esse pacote como **cache de demonstração** dos 3 pontos de demo.

## 5. WhatsApp (Meta Cloud API)
1. No painel da Meta: crie o app, adicione o produto WhatsApp e o número. Anote **Phone number ID**, **token permanente** (usuário do sistema) e o **App Secret**.
2. **Webhook:** URL de callback `https://seu-dominio/webhooks/whatsapp`, token de verificação = o valor de `WHATSAPP_VERIFY_TOKEN`; assine o campo `messages`. A Meta faz um GET de verificação: o BALK responde o `hub.challenge`.
3. Cada POST traz `X-Hub-Signature-256`; o BALK **rejeita** o que não bater com `WHATSAPP_APP_SECRET`. Mensagens repetidas (a Meta reenvia) são ignoradas pelo id.
4. **Regras de janela:** quando o produtor escreve primeiro, as respostas dentro de 24 h são texto livre (é o que a conversa de cadastro e o primeiro relatório usam). Os **alertas diários são proativos**: precisam de **template aprovado**.
5. **Template:** categoria **Utilidade**, idioma pt_BR, corpo `BALK: {{1}}` (uma variável com a mensagem do alerta). O BALK troca as quebras de linha por " | " antes de enviar (confirme na documentação da Meta as regras de variáveis). Textos promocionais são classificados como marketing e custam bem mais. Coloque o nome em `WHATSAPP_TEMPLATE_NAME`.
6. **Custos** (conferir na tabela oficial, que muda): desde 1º/10/2026 mensagens de serviço depois das 1.000 gratuitas por número e templates de utilidade são cobrados (referência para o Brasil: cerca de R$ 0,035 por mensagem). Com 8 alertas por mês são ~R$ 0,28 por produtor, fora a IA.
7. Teste com o **número de teste da Meta** e 2 ou 3 números verificados antes de qualquer produtor real.
8. Não use automação não oficial do WhatsApp (Baileys e afins): viola os termos.
9. **Dois templates, não um:** (a) **alerta** (utilidade, `BALK: {{1}}`, já descrito) e (b) **convite/boas-vindas** (utilidade; texto neutro como "A cooperativa X cadastrou você para receber avisos de clima e lavoura. Responda SIM para aceitar ou SAIR para não receber"). O convite é o que o BALK envia a quem foi cadastrado por uma cooperativa e ao sucessor; sem ele aprovado, esses convites não saem.
10. **Estados da mensagem:** assine também os eventos de status no mesmo webhook (a Meta manda `statuses` junto). O BALK grava enviada, entregue, lida ou falhou na tabela `messages` (`GET /producers/<id>/...` ainda não expõe; consulte o banco ou `python -m app.cli export-producer`).
11. **Reserva por SMS:** se o envio no WhatsApp falhar 2 vezes, o alerta sai por SMS (texto de 160 caracteres) quando a Twilio está configurada. Sem Twilio, a mensagem fica marcada `failed` e **não** entra no silêncio, então o BALK tenta de novo no ciclo seguinte.

## 5-B. O site (cadastro com código e mapa dos talhões)
1. **Código de verificação = template de AUTENTICAÇÃO** na Meta (categoria própria, corpo com o código, geralmente botão de copiar). Crie e coloque o nome em `WHATSAPP_CODE_TEMPLATE_NAME`.
   Sem ele o código usa o template geral de utilidade, que a Meta pode reprovar por ser outra finalidade. **O envio real do código não foi testado** (sem conta Meta); o texto livre só chega se o produtor escreveu nas últimas 24 h.
2. **Convite ao segundo contato:** `WHATSAPP_INVITE_TEMPLATE_NAME` (seção 5, item 9).
3. **Satélite na demo (MapTiler, plano gratuito):** crie a conta em `cloud.maptiler.com` (sem cartão), copie a chave e coloque em `MAPTILER_KEY`. O mapa passa a abrir em satélite, com botão para alternar para ruas.
   Verificado na página de preços (26/11/2026): o plano gratuito é para teste, protótipo e uso pessoal ou **não comercial**, inclui 100 mil requisições por mês (uma imagem de 256 px conta 1) e **pausa o serviço** ao esgotar a cota até o mês seguinte; exige o **logotipo do MapTiler** no mapa.
   O BALK mostra a atribuição escrita "© MapTiler"; **o logotipo em si ainda não foi adicionado** (confira as regras de uso no site deles antes da apresentação). A chave aparece nas requisições do navegador: restrinja-a ao seu domínio no painel do MapTiler e **não** a coloque no repositório.
   Uso comercial (produtor pagando) exige o plano Flex (US$ 30 por mês + extras) ou outro provedor. **Não testado com chave real** (sem conta): o formato da URL vem da documentação deles.
   **Fundo do mapa em produção (decisão humana):** o padrão é o servidor público do OpenStreetMap, aceitável para demonstração e baixo volume, mas a política de uso dele **não permite uso pesado** e exige atribuição.
   Antes de abrir para muitos produtores, contrate um provedor de mapas (ou hospede os seus) e troque `MAP_TILES_URL`/`MAP_TILES_ATTRIBUTION`. Imagem de satélite como fundo ajuda o produtor a reconhecer a lavoura, mas tem termos próprios: leia antes.
4. **Sessão e limites:** cookie `balk_session` por 30 dias; código de 6 dígitos válido por 10 min, 5 tentativas, 3 pedidos por hora por telefone, 10 por hora por IP, 60 s entre pedidos. Os limites por IP em memória (`RateLimiter`) valem por processo; atrás de proxy, repasse `X-Forwarded-For` e limite também no proxy.
5. **Texto de consentimento do site** é o de `consent.yaml` (v0, provisório). **Revisão jurídica (LGPD) antes de qualquer produtor real.** Mudou o texto: suba `versao`.
6. **Endurecimento (auditoria de segurança de 26/11/2026):** `BALK_ENV` só aceita `dev` ou `production` (valor inválido impede de subir). O BALK **não lê `X-Forwarded-For`** (era forjável e anulava os limites):
   atrás de proxy defina `FORWARDED_ALLOW_IPS=<IP do proxy>` para o uvicorn repassar o IP real. A imagem sobe com `--no-access-log` (o log do uvicorn gravaria os tokens de `/r/`, `/h/` e `/m/`).
   Limites por conta: 3 convites e 3 envios de relatório por dia. `POST /jobs/purge` (cron diário) também apaga verificações com mais de 24 h, sessões vencidas e links gastos.
   Nada disso foi testado atrás de um proxy real.
7. **O que o produtor pode fazer sozinho** em `/app/meus.html`: ver talhões, convidar ou retirar o segundo contato, baixar os dados, parar de receber e apagar a conta.

## 6. SMS (Twilio)
1. Webhook de mensagem recebida: `https://seu-dominio/sms/inbound` (POST). O BALK valida `X-Twilio-Signature` com `TWILIO_AUTH_TOKEN` e responde com TwiML (a Twilio envia a resposta ao produtor).
2. A assinatura é calculada sobre a URL exata: `PUBLIC_BASE_URL` precisa ser igual à URL cadastrada na Twilio (atenção a `https`, domínio e porta).
3. SMS: até 160 caracteres, sem acento; **sem link** por padrão (o projeto prevê SMS para quem tem pouca internet). `SMS_INCLUDE_LINK=1` põe o link quando couber.
4. Confirme remetente e regras de cadastro prévio no Brasil. Testes só para números verificados.

## 7. Rotina diária, n8n e cron
- **Alertas do dia:** `POST /jobs/daily` com a chave (`X-API-Key`), às **06:05** (depois do horário quieto, que vai até as 6h). Pode ser cron do servidor:
  `5 6 * * * curl -fsS -X POST -H "X-API-Key: $BALK_API_KEY" https://seu-dominio/jobs/daily`
  ou o fluxo `n8n/wf2_diario.json`.
- **n8n (opcional):** importe os JSON de `n8n/`, crie a credencial **Header Auth** chamada "BALK API key" (nome do header `X-API-Key`, valor = `BALK_API_KEY`) e as de Meta/Twilio **pela interface** (nunca no JSON). Estes fluxos nunca foram importados num n8n real: confira os nós.
- Se o webhook da Meta apontar direto para o BALK, o WF1 do n8n não é necessário.
- **n8n é opcional.** O padrão é cron + `POST /jobs/daily`. A resposta traz `erros`: produtores cuja análise falhou (clima fora do ar etc.) são pulados e **não recebem alerta**; monitore essa lista.
- **Produção nunca simula:** com `BALK_ENV=production`, `DATA_MODE=auto` vale como `real`. Se o satélite falhar, o relatório diz "sem imagem adequada" e só há aviso de clima; se o clima falhar, o produtor é pulado.
- **CSV de cooperativa:** em produção cada produtor do CSV recebe um **convite** e só passa a receber avisos depois de responder SIM (aceite registrado com a versão do texto). Em dev vale a declaração da cooperativa. `CSV_REQUIRES_OPTIN=1/0` força.

## 8. Dia a dia
- **Saúde:** `GET /health` (liveness, público) e `GET /ready` (com chave: banco, modo, pendências e quais canais estão ligados, sem segredos).
- **Logs:** uma linha JSON por requisição (`evt`, `rid`, método, caminho, status, ms). O token do relatório e o telefone **não** vão para o log. Alerte em: respostas 5xx, `evt: erro_interno`, falhas de envio, `/health` fora.
- **Backup:** `python -m app.cli backup /caminho/backup.db` (seguro com o servidor ligado). Faça diário e guarde fora do servidor.
- **Limpeza:** `python -m app.cli purge-reports` apaga relatórios vencidos e as imagens (ou `POST /jobs/purge`).
- **LGPD:** `python -m app.cli export-producer <telefone>` (cópia dos dados) e `python -m app.cli delete-producer <telefone>` (apaga tudo: produtor, análises, alertas, relatórios e arquivos) ou `DELETE /producers/<id>` com a chave. `SAIR` pelo canal já desativa e retira o consentimento. Defina e publique a política de retenção.
- **Escalonamento humano:** a resposta `2` grava em `escalations`; ligue isso a um e-mail ou chat da equipe (ainda não existe notificação automática).

## 9. Checklist de entrada em produção
Marque só o que você **viu funcionar**.
- [ ] `python -m app.cli check` sem pendências em `BALK_ENV=production`
- [ ] HTTPS válido e `GET /health` responde pelo domínio
- [ ] `check_apis.py` com as 5 fontes OK a partir do servidor
- [ ] Um pacote real (`meta.json` com `earth-search`) e relatório sem aviso de simulado
- [ ] Declividade e NDVI conferidos contra o QGIS manual em 1 ponto conhecido
- [ ] Agrônomo revisou `crops.yaml` e `rules.yaml` (ou o piloto está declarado como "em revisão")
- [ ] Webhook da Meta verificado, assinatura rejeita corpo adulterado, template aprovado
- [ ] Webhook da Twilio com assinatura válida e resposta TwiML recebida no celular
- [ ] Conversa completa de cadastro em um celular real (consentimento, pin, cultura, data) e primeiro relatório com link e mapa
- [ ] `SAIR` desativa; `delete-producer` apaga
- [ ] Backup agendado e **restauração testada**
- [ ] Plano comercial do Open-Meteo (se houver cobrança) e custos de mensagem conferidos
- [ ] Política de privacidade publicada e consentimento registrado
- [ ] Teste de entendimento das mensagens com 3 a 5 produtores
- [ ] Texto de consentimento (`consent.yaml`, hoje **v0 provisório**) revisado por advogado; versão subida e política de privacidade publicada
- [ ] Convite de opt-in (cooperativa/sucessor) com template aprovado e testado: o CSV de 1 número real autorizado chega, responde SIM e vira ativo
- [ ] Reserva por SMS testada: derrube o token do WhatsApp de propósito e confira que o alerta chegou por SMS e ficou registrado
- [ ] Backtest rodado de novo na época e região do piloto (`python -m app.cli backtest`) e o limite de geada ajustado com o agrônomo
- [ ] Demo da final com dado **ambiental real** em cache (só identidade e telefone sintéticos)

## 10. Limites conhecidos (seja honesto com o cliente)
- Resolução de 10 m e área de ~7 ha: talhão pequeno mistura vizinhos.
- Satélite não é tempo real; nuvem esconde a lavoura. A confiança cai com a idade da cena.
- Erosão, baixada contra geada, umidade contra clima, estresse e colheita são **hipóteses** (`[H]`) ou premissas.
- Um processo só: limite de requisições em memória e SQLite. Para vários servidores, troque por Postgres e um proxy com limite.
- Sem painel para a cooperativa além da tabela do simulador; sem áudio; sem segundo contato (sucessor).
