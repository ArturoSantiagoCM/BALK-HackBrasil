# Guia passo a passo: BALK com WhatsApp e SMS de verdade

Para rodar o BALK em outro computador com as mensagens chegando num celular de verdade: o nosso no vídeo e o dos
avaliadores. Um Android com um chip dedicado faz os dois canais com o mesmo número, como no projeto.

| Canal | Ferramenta | Licença | No BALK |
|---|---|---|---|
| WhatsApp | [OpenWA](https://github.com/rmyndharis/OpenWA), um gateway pareado pelo QR, como o WhatsApp Web | MIT | `OPENWA_*` no `.env`. Recebe em `POST /webhooks/openwa` |
| SMS | [SMS Gateway for Android](https://github.com/capcom6/android-sms-gateway), um app no celular do chip | Apache-2.0 | `SMSGATE_*` no `.env`. Recebe em `POST /webhooks/smsgate` |

Nenhum código dessas ferramentas entra no repositório. O BALK só conversa com a API delas.

**Status.** O envio, a leitura dos webhooks, as assinaturas e uma conversa inteira foram testados contra o formato
documentado de cada ferramenta (`tests/test_canais_reais.py`, sem internet). Os gateways rodando de verdade, com o chip
pareado, ainda **não** foram testados. A primeira vez é o passo 9 deste guia.

Os comandos estão em PowerShell, para Windows. No Linux, os equivalentes estão indicados.

## Como a mensagem chega ao celular

**WhatsApp:**
1. O OpenWA é um "WhatsApp Web" sem tela, rodando no servidor e conectado ao número do chip como aparelho conectado.
2. Quando o produtor escreve, o WhatsApp entrega a mensagem ao celular do chip e também ao OpenWA.
3. O OpenWA avisa o BALK (`POST /webhooks/openwa`, assinado com `OPENWA_WEBHOOK_SECRET`). O BALK confere a assinatura,
   responde na hora e processa em segundo plano.
4. Para responder, o BALK pede ao OpenWA o id certo do número e manda o texto (`send-text`). Se houver mapa, a imagem
   vai junto, em base64.
5. A confirmação de entrega e de leitura volta pelo mesmo webhook e fica registrada na mensagem.
6. Se o número não tiver WhatsApp ou o envio falhar duas vezes, o aviso cai para o SMS.

Depois do QR, o celular do chip pode ficar desligado por alguns dias sem derrubar o WhatsApp. Se ficar 14 dias sem se
conectar, o WhatsApp desconecta os aparelhos conectados.

**SMS:**
1. O produtor manda o SMS para o número do chip. O app SMS Gateway recebe e chama o BALK direto do celular
   (`POST /webhooks/smsgate`, assinado com a Signing Key e com horário).
2. Para responder, o BALK pede ao servidor do app (`api.sms-gate.app`) que envie o SMS. O servidor avisa o celular, e o
   celular envia pela operadora.
3. Por isso o celular do chip precisa ficar ligado, com internet e com o app aberto. Ele é o ponto mais frágil.

**Avisos do dia, código do site e convite do sucessor** saem pelo mesmo caminho, só que começam no BALK (o cron chama
`/jobs/daily`, o site pede um código). O BALK escolhe o canal de cada produtor (WhatsApp ou SMS) como antes. Só o
"carteiro" mudou: no lugar da Meta e da Twilio, o OpenWA e o celular com chip.

**O que muda em relação ao projeto com a Meta e a Twilio:**
- Não há template aprovado. O aviso fora da janela de 24 horas sai como texto comum, com o risco de bloqueio que isso
  traz.
- A entrega não tem a garantia de um provedor oficial.
- O volume precisa ser baixo: poucas mensagens por minuto e só para quem pediu.

---

## 0. O que você precisa

- **Computador:** com internet. Ele fica ligado durante o teste e o vídeo.
- **Python 3.12:** [python.org](https://www.python.org/downloads/). Na instalação, marque "Add python.exe to PATH".
- **Node.js 22 ou mais novo:** [nodejs.org](https://nodejs.org/), versão LTS. É para o OpenWA. Outra opção é o Docker Desktop.
- **Git:** [git-scm.com](https://git-scm.com/).
- **Um Android (5.0 ou mais novo) com um chip só para isso:** com crédito ou plano de SMS e com internet. Nunca use o
  seu número pessoal, porque o gateway não é oficial e o número pode ser restringido.
- **Outro celular para fazer o papel do produtor:** um smartphone para o WhatsApp e, de preferência, um aparelho
  simples para o SMS.

Você vai deixar **3 janelas do PowerShell** abertas ao mesmo tempo: OpenWA, túnel e BALK.

---

## 1. Pegar o código do BALK

O código mais novo precisa estar no GitHub. Confira o último commit em
<https://github.com/ArturoSantiagoCM/BALK-HackBrasil/commits/main>.

```powershell
cd $HOME\Desktop
git clone https://github.com/ArturoSantiagoCM/BALK-HackBrasil.git
cd BALK-HackBrasil
```

Se o envio ao GitHub ainda não tiver sido feito, copie a pasta do projeto por pendrive ou zip. Deixe de fora `.venv`,
`balk.db`, `work`, `__pycache__` e o `.env`.

## 2. Instalar o BALK e conferir que ele roda

```powershell
python --version                      # tem que mostrar 3.12.x
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Se o PowerShell bloquear o `Activate.ps1`, rode uma vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e
tente de novo. No Linux, use `python3.12 -m venv .venv` e `source .venv/bin/activate`.

Teste rápido, ainda sem celular:

```powershell
$env:DATA_MODE = "simulado"
python -m uvicorn app.main:app --port 8000
```

Abra <http://localhost:8000/demo/index.html> e mande "Oi" no celular do simulador. Se a resposta chegar, o BALK está
instalado. Feche com Ctrl+C e rode `Remove-Item Env:DATA_MODE`.

## 3. Preparar o celular do chip (uma vez)

1. Coloque o chip e confirme que ele envia e recebe SMS e tem internet.
2. Instale o **WhatsApp** (ou o WhatsApp Business) com esse número. Converse um pouco com 2 ou 3 contatos salvos, como
   uma pessoa normal faria. Número novo que já começa disparando mensagens chama atenção.
3. Instale o **SMS Gateway for Android**. Baixe o `.apk` da
   [página de versões](https://github.com/capcom6/android-sms-gateway/releases) e permita instalar de fonte externa.
4. Abra o app e dê as permissões de **enviar SMS** e **receber SMS**.
5. Ligue o **Cloud Server** e toque em **Start Service**. Quando o app pedir, crie o registro. Anote o **usuário** e a
   **senha** que aparecem na seção Cloud Server.
6. Em **Settings → Webhooks → Signing Key**, anote a **chave de assinatura**.
7. Deixe o app sem economia de bateria (Configurações do Android → Apps → SMS Gateway → Bateria → Sem restrições).
   O celular fica ligado e carregando durante todo o teste.

## 4. Rodar o OpenWA e parear o WhatsApp do chip

Na **janela 1**:

```powershell
cd $HOME\Desktop
git clone https://github.com/rmyndharis/OpenWA.git
cd OpenWA
npm ci
npm run dev
```

O `npm ci` baixa bastante coisa, inclusive o Chromium, e leva alguns minutos. Deixe essa janela aberta.

Com o Docker, em vez do Node: `docker compose -f docker-compose.dev.yml up -d`. O painel fica em
<http://localhost:2785>, e a chave sai com `docker exec openwa-api cat /app/data/.api-key`.

1. Pegue a chave de administrador. Numa janela nova, rode `Get-Content $HOME\Desktop\OpenWA\data\.api-key` e copie
   só a chave. Essa é a `OPENWA_API_KEY`.
2. Abra o painel em <http://localhost:2886> e entre com essa chave.
3. Crie uma sessão chamada `balk` e clique para iniciar. Vai aparecer um QR.
4. No celular do chip, abra o WhatsApp → **Aparelhos conectados** → **Conectar um aparelho** e leia o QR.
5. Espere a sessão ficar **ready** no painel. Copie o **id da sessão**, que é a `OPENWA_SESSION`.

Se o celular pedir para "criar uma chave de acesso" (passkey) e a sessão não passar de `qr_ready`, é um bloqueio do
próprio WhatsApp para alguns números, e o OpenWA não consegue contornar. Use outro número.

## 5. Abrir um endereço público com https (túnel)

O link do relatório precisa abrir no celular do produtor, e o app de SMS precisa alcançar o BALK. Um túnel gratuito da
Cloudflare faz isso sem servidor e sem domínio.

Na **janela 2**:

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8000
```

Se o `winget` não existir, baixe o `cloudflared-windows-amd64.exe` em
<https://github.com/cloudflare/cloudflared/releases> e rode-o no lugar de `cloudflared`.

O comando mostra um endereço como `https://palavras-aleatorias.trycloudflare.com`. **Copie esse endereço.** Ele vale
enquanto a janela estiver aberta. Se fechar ou cair, o endereço muda, e é preciso refazer os passos 6 e 8.

## 6. Criar o `.env` do BALK

Na pasta do BALK, gere 3 segredos aleatórios. Rode o comando 3 vezes e guarde os resultados:

```powershell
python -c "import secrets;print(secrets.token_urlsafe(32))"
```

Crie o arquivo `.env` na pasta do BALK com este conteúdo, trocando o que está entre `< >`:

```
BALK_ENV=dev
DATA_MODE=real
PUBLIC_BASE_URL=https://<seu-endereco>.trycloudflare.com
BALK_API_KEY=<segredo 1>
BALK_AUTH_SECRET=<segredo 2>

OPENWA_URL=http://localhost:2785
OPENWA_SESSION=<id da sessão do passo 4>
OPENWA_API_KEY=<chave do OpenWA do passo 4>
OPENWA_WEBHOOK_SECRET=<segredo 3>

SMSGATE_URL=https://api.sms-gate.app/3rdparty/v1
SMSGATE_USER=<usuário do app, passo 3>
SMSGATE_PASSWORD=<senha do app, passo 3>
SMSGATE_WEBHOOK_KEY=<Signing Key do app, passo 3>
```

- `DATA_MODE=real` usa satélite, relevo, solo e clima de verdade. O primeiro relatório leva cerca de 1 minuto por
  talhão. Para um vídeo mais rápido, use `DATA_MODE=simulado`, mas o relatório vai avisar que os dados são simulados.
  O canal não muda: com o `.env` acima, a mensagem vai para o celular de verdade nos dois modos.
- Com `BALK_API_KEY` definida, o simulador (`/demo`) ainda não funciona, porque ele não manda a chave. Com o túnel aberto,
  **não** apague a chave: sem ela, qualquer pessoa com o endereço veria os dados e os códigos do site.
- O `.env` nunca vai para o GitHub (já está no `.gitignore`).

## 7. Subir o BALK

Na **janela 3**, dentro da pasta do BALK:

```powershell
.venv\Scripts\Activate.ps1
python -m app.cli check
python -m uvicorn app.main:app --port 8000 --proxy-headers
```

O `check` lista as variáveis definidas e testa as fontes externas. Depois, abra
`https://<seu-endereco>.trycloudflare.com/health` no navegador. Tem que aparecer `"whatsapp":"openwa"` e
`"sms":"celular"`.

## 8. Ligar os webhooks (cada vez que o endereço do túnel mudar)

Numa janela nova do PowerShell, preencha as 6 primeiras linhas e rode o bloco inteiro:

```powershell
$BASE   = "https://<seu-endereco>.trycloudflare.com"
$OWKEY  = "<OPENWA_API_KEY>"
$SESSAO = "<OPENWA_SESSION>"
$OWSEC  = "<OPENWA_WEBHOOK_SECRET>"
$SGUSER = "<SMSGATE_USER>"
$SGPASS = "<SMSGATE_PASSWORD>"

# WhatsApp: o OpenWA avisa o BALK de cada mensagem recebida e de cada confirmação de entrega
$corpo = @{ url = "$BASE/webhooks/openwa"; events = @("message.received", "message.ack"); secret = $OWSEC } | ConvertTo-Json
Invoke-RestMethod -Method Post "http://localhost:2785/api/sessions/$SESSAO/webhooks" -Headers @{ "X-API-Key" = $OWKEY } -ContentType "application/json" -Body $corpo

# SMS: o app do celular avisa o BALK de cada SMS recebido
$auth  = "Basic " + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${SGUSER}:${SGPASS}"))
$corpo = @{ id = "balk"; url = "$BASE/webhooks/smsgate"; event = "sms:received" } | ConvertTo-Json
Invoke-RestMethod -Method Post "https://api.sms-gate.app/3rdparty/v1/webhooks" -Headers @{ Authorization = $auth } -ContentType "application/json" -Body $corpo
```

Se o endereço mudar, rode o bloco de novo. Se o cadastro do SMS reclamar do `id` repetido, apague o antigo e cadastre
outra vez:
`Invoke-RestMethod -Method Delete "https://api.sms-gate.app/3rdparty/v1/webhooks/balk" -Headers @{ Authorization = $auth }`.
No OpenWA, apague o webhook antigo pelo painel, na sessão, em Webhooks.

Antes de gravar, confira as duas pontas sem gastar uma conversa:

```powershell
Invoke-RestMethod -Method Post "http://localhost:2785/api/sessions/$SESSAO/webhooks/<id-do-webhook>/test" -Headers @{ "X-API-Key" = $OWKEY }
```

O `<id-do-webhook>` aparece na resposta do cadastro acima. Na janela do BALK deve aparecer um `POST /webhooks/openwa`
com resposta 200.

## 9. Testar (é o roteiro do vídeo)

1. **WhatsApp:** do celular do "produtor", mande **Oi** para o número do chip. Responda **SIM**. Mande a localização
   (📎 → Localização → enviar a localização atual, ou um ponto numa lavoura). Mande **soja** e depois a data de
   plantio, por exemplo **20/10**. Chega uma resposta a cada passo. No fim chegam o relatório, a imagem do mapa e o
   link. Abra o link no celular.
2. **Site:** abra `https://<seu-endereco>.trycloudflare.com/app/` e digite o mesmo número. O código chega no WhatsApp.
   Desenhe um talhão no mapa e conclua: chega um relatório por talhão.
3. **SMS:** de um celular simples, mande **BALK soja 20/10 Sorriso MT** para o número do chip. Responda **SIM**. As
   respostas chegam por SMS, saindo do próprio celular do chip.
4. **Aviso do dia:** na janela do passo 8, rode:
   ```powershell
   $BALKKEY = "<BALK_API_KEY>"
   Invoke-RestMethod -Method Post "http://localhost:8000/jobs/daily" -Headers @{ "X-API-Key" = $BALKKEY }
   ```
   Os produtores com alerta recebem o aviso com "Responda 1… 2…". Responda **2** no celular e veja o pedido para a
   equipe:
   ```powershell
   Invoke-RestMethod "http://localhost:8000/escalations" -Headers @{ "X-API-Key" = $BALKKEY }
   ```
   O aviso só sai se houver motivo (chuva, vento, geada, colheita). Sem motivo, `enviados` vem vazio, e isso está certo.

## 10. Se algo não chegar

Olhe nesta ordem:

1. **Janela do BALK:** a mensagem entrou (`POST /webhooks/openwa` ou `/webhooks/smsgate`)? Um `401` quer dizer que o
   segredo ou a chave no `.env` não bate com o do webhook (passo 8). Um `503` quer dizer que falta o segredo no `.env`.
2. **Painel do OpenWA:** a sessão está `ready`? Na sessão, em Webhooks, há falhas de entrega?
3. **App do celular:** a fila de webhooks tem erro? O serviço está ligado? Há crédito para SMS?
4. **Túnel:** a janela 2 ainda está aberta, e o endereço é o mesmo do `.env`?
5. **`/health`:** mostra `openwa` e `celular`? Se não, o `.env` não foi lido. O BALK precisa ser iniciado dentro da
   pasta onde o `.env` está.

Outros problemas comuns:

- **A primeira mensagem para um contato novo às vezes não chega.** É uma política do WhatsApp. Por isso o produtor
  escreve primeiro.
- **O número pode ter sido digitado com ou sem o 9.** O BALK pergunta ao OpenWA o id certo de cada número antes de
  enviar, e trata as duas formas como a mesma pessoa.
- **Com `DATA_MODE=real`, a resposta final demora cerca de 1 minuto.** O BALK está baixando a imagem de satélite.
  Espere.

## 11. Deixar no ar para os avaliadores (até o fim da avaliação)

O túnel do passo 5 cai se o computador desligar ou dormir. Para alguns dias de avaliação há dois caminhos.

**A. O mesmo computador ligado direto (mais simples).**
- Desligue a suspensão do Windows.
- Mantenha as 3 janelas abertas e o celular carregando.
- Mande aos avaliadores o número do chip, o endereço do site e o roteiro do passo 9.
- Risco: se o túnel reiniciar, o endereço muda, e é preciso refazer os passos 6 e 8 e mandar o endereço novo.

**B. Um servidor pequeno (mais estável).**
1. Contrate uma VPS Linux com 2 vCPU, 4 GB de RAM e Docker.
2. Para ter https sem comprar domínio, use `<ip-com-traços>.sslip.io` (por exemplo `203-0-113-5.sslip.io`) com o Caddy
   na frente: `caddy reverse-proxy --from 203-0-113-5.sslip.io --to localhost:8000`.
3. No `.env`, use `BALK_ENV=production`, `PUBLIC_BASE_URL=https://203-0-113-5.sslip.io` e `OPENWA_URL=http://openwa:2785`.
   Em produção o BALK recusa subir sem chave, segredo e https, e o simulador fica desligado.
4. Rode `docker compose --profile openwa up -d --build` para subir o BALK e o OpenWA. Esse perfil ainda não foi testado.
5. Para abrir o painel do OpenWA, use um túnel SSH: `ssh -L 2785:localhost:2785 usuario@servidor`, e depois
   <http://localhost:2785>.
6. Pareie o QR de novo e cadastre o webhook do OpenWA com `http://api:8000/webhooks/openwa`.
7. O webhook do SMS vai para `https://203-0-113-5.sslip.io/webhooks/smsgate`.
8. Para o aviso diário às 06:05, crie no servidor um cron:
   `5 6 * * * curl -fsS -X POST http://localhost:8000/jobs/daily -H "X-API-Key: <BALK_API_KEY>"`.

## 12. Ao terminar

- Feche o túnel (janela 2) quando não estiver testando. Sem ele, ninguém de fora alcança o BALK.
- Para desfazer o pareamento, vá no celular do chip → WhatsApp → Aparelhos conectados → desconectar.
- Os dados de teste ficam no `balk.db` da pasta. Para apagar um produtor:
  `python -m app.cli delete-producer +55DDDNUMERO`.
- **Para escala e produção,** o caminho continua sendo o oficial: a WhatsApp Cloud API da Meta, com templates
  aprovados, e um provedor de SMS com contrato. Os dois já estão no código (`WHATSAPP_*` e `TWILIO_*` no
  `.env.example`). O OpenWA e o celular com chip servem para a demonstração.
