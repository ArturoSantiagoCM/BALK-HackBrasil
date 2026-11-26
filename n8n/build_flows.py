"""Gera os 4 fluxos do n8n (JSON) em n8n/. Rode: python n8n/build_flows.py

Os fluxos só chamam endpoints do FastAPI e enviam mensagens; nenhuma regra de negócio fica no n8n.
STATUS: gerados por script e NÃO importados num n8n real nesta máquina (sem Docker). Importe cada JSON
(Workflows > Import from file), crie as credenciais pela interface e confira os campos dos nós.
"""
import json
from pathlib import Path

API = "http://api:8000"
OUT = Path(__file__).parent


def node(name, type_, params, pos, version=1, **extra):
    return {"name": name, "type": f"n8n-nodes-base.{type_}", "typeVersion": version, "position": pos,
            "parameters": params, **extra}


def http(name, method, path, pos, body=None, **extra):
    # A chave da API (BALK_API_KEY) vai por credencial "Header Auth" criada na interface do n8n (nome do header: X-API-Key).
    p = {"method": method, "url": f"{API}{path}", "options": {}, "authentication": "genericCredentialType",
         "genericAuthType": "httpHeaderAuth"}
    if body is not None:
        p.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
    return node(name, "httpRequest", p, pos, 4.2, onError="continueErrorOutput",
                credentials={"httpHeaderAuth": {"id": "", "name": "BALK API key"}}, **extra)


def erro(pos):
    # Aviso à equipe quando uma chamada ao FastAPI falhar (URL do aviso vem de uma variável de ambiente).
    n = http("Avisar equipe (erro)", "POST", "", pos).copy() | {
        "parameters": {"method": "POST", "url": "={{$env.ALERT_WEBHOOK_URL}}", "sendBody": True,
                       "specifyBody": "json", "jsonBody": '={"text": "BALK: falha em " + $workflow.name}', "options": {}}}
    n.pop("credentials", None)  # a chave da API do BALK nunca vai para o webhook de aviso
    n.pop("onError", None)
    return n


def wire(*links):
    c = {}
    for src, dst, out in links:
        c.setdefault(src, {"main": []})
        while len(c[src]["main"]) <= out:
            c[src]["main"].append([])
        c[src]["main"][out].append({"node": dst, "type": "main", "index": 0})
    return c


def flow(name, nodes, connections):
    return {"name": name, "nodes": nodes, "connections": connections, "active": False,
            "settings": {"executionOrder": "v1"}, "meta": {"templateCredsSetupCompleted": False}}


def send_nodes(x, y):
    """Envio por canal: credenciais SEMPRE pela interface do n8n (nunca no JSON)."""
    return [
        node("Canal", "switch", {"rules": {"values": [
            {"conditions": {"conditions": [{"leftValue": "={{$json.channel}}", "rightValue": "whatsapp",
                                            "operator": {"type": "string", "operation": "equals"}}]}, "renameOutput": True, "outputKey": "whatsapp"},
            {"conditions": {"conditions": [{"leftValue": "={{$json.channel}}", "rightValue": "sms",
                                            "operator": {"type": "string", "operation": "equals"}}]}, "renameOutput": True, "outputKey": "sms"}]}},
             [x, y], 3),
        node("Enviar WhatsApp (Meta Cloud API)", "httpRequest", {
            "method": "POST", "url": "=https://graph.facebook.com/v21.0/{{$env.WHATSAPP_PHONE_ID}}/messages",
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth", "sendBody": True,
            "specifyBody": "json", "jsonBody": '={"messaging_product":"whatsapp","to":"{{$json.phone}}","type":"text","text":{"body":{{JSON.stringify($json.text)}}}}'},
             [x + 260, y - 80], 4.2),
        node("Enviar SMS (Twilio)", "twilio", {"operation": "send", "from": "={{$env.TWILIO_FROM}}", "to": "={{$json.phone}}",
                                              "message": "={{$json.text}}"}, [x + 260, y + 80], 1),
    ]


def wf1():
    n = [node("Webhook do canal", "webhook", {"httpMethod": "POST", "path": "balk-entrada", "responseMode": "lastNode"},
              [0, 0], 2),
         http("POST /conversation", "POST", "/conversation", [260, 0],
              '={"phone": "{{$json.body.phone}}", "text": "{{$json.body.text}}", "channel": "{{$json.body.channel}}"}'),
         node("Texto da resposta", "set", {"assignments": {"assignments": [
             {"name": "phone", "value": "={{$('Webhook do canal').item.json.body.phone}}", "type": "string"},
             {"name": "channel", "value": "={{$('Webhook do canal').item.json.body.channel}}", "type": "string"},
             {"name": "text", "value": "={{$json.reply}}", "type": "string"}]}}, [520, 0], 3.4),
         *send_nodes(780, 0), erro([260, 200])]
    c = wire(("Webhook do canal", "POST /conversation", 0), ("POST /conversation", "Texto da resposta", 0),
             ("POST /conversation", "Avisar equipe (erro)", 1), ("Texto da resposta", "Canal", 0),
             ("Canal", "Enviar WhatsApp (Meta Cloud API)", 0), ("Canal", "Enviar SMS (Twilio)", 1))
    return flow("BALK WF1 Entrada (cadastro por conversa)", n, c)


def wf2():
    code = ("const r = $json; const out = [];\n"
            "const alerts = r.messages.filter(m => m.kind === 'alert');\n"
            "alerts.forEach(m => out.push({json: {producer_id: r.producer_id, phone: r.phone, channel: r.channel, type: m.type, text: m.text}}));\n"
            "return out;")
    n = [node("Todo dia 06:05", "scheduleTrigger", {"rule": {"interval": [{"field": "cronExpression", "expression": "5 6 * * *"}]}},
              [0, 0], 1.2),
         http("GET /producers/active", "GET", "/producers/active", [240, 0]),
         node("Um produtor por vez", "splitInBatches", {"batchSize": 1}, [480, 0], 3),
         http("POST /analyze/{id}", "POST", "/analyze/{{$json.id}}", [720, 0]),
         node("Alertas da análise", "code", {"jsCode": code}, [960, 0], 2),
         *send_nodes(1200, 0),
         http("POST /alerts/log", "POST", "/alerts/log", [1700, 0],
              '={"producer_id": {{$("Alertas da análise").item.json.producer_id}}, "type": "{{$("Alertas da análise").item.json.type}}"}'),
         erro([720, 200])]
    n[3]["parameters"]["url"] = f"={API}/analyze/{{{{$json.id}}}}"
    c = wire(("Todo dia 06:05", "GET /producers/active", 0), ("GET /producers/active", "Um produtor por vez", 0),
             ("Um produtor por vez", "POST /analyze/{id}", 1), ("POST /analyze/{id}", "Alertas da análise", 0),
             ("POST /analyze/{id}", "Avisar equipe (erro)", 1), ("Alertas da análise", "Canal", 0),
             ("Canal", "Enviar WhatsApp (Meta Cloud API)", 0), ("Canal", "Enviar SMS (Twilio)", 1),
             ("Enviar WhatsApp (Meta Cloud API)", "POST /alerts/log", 0), ("Enviar SMS (Twilio)", "POST /alerts/log", 0),
             ("POST /alerts/log", "Um produtor por vez", 0))
    return flow("BALK WF2 Diário (alertas do dia)", n, c)


def wf3():
    n = [node("Webhook /ingest", "webhook", {"httpMethod": "POST", "path": "balk-ingest", "responseMode": "lastNode"}, [0, 0], 2),
         http("POST /ingest/producers", "POST", "/ingest/producers?analisar=true", [260, 0], "={{JSON.stringify($json.body)}}"),
         node("Um relatório por produtor", "splitOut", {"fieldToSplitOut": "relatorios"}, [520, 0], 1),
         node("Texto do relatório", "set", {"assignments": {"assignments": [
             {"name": "phone", "value": "={{$json.phone}}", "type": "string"},
             {"name": "channel", "value": "={{$json.channel}}", "type": "string"},
             {"name": "text", "value": "={{$json.messages[0].text}}", "type": "string"}]}}, [780, 0], 3.4),
         *send_nodes(1040, 0), erro([260, 200])]
    c = wire(("Webhook /ingest", "POST /ingest/producers", 0), ("POST /ingest/producers", "Um relatório por produtor", 0),
             ("POST /ingest/producers", "Avisar equipe (erro)", 1), ("Um relatório por produtor", "Texto do relatório", 0),
             ("Texto do relatório", "Canal", 0), ("Canal", "Enviar WhatsApp (Meta Cloud API)", 0), ("Canal", "Enviar SMS (Twilio)", 1))
    return flow("BALK WF3 Novo produtor (CSV da cooperativa)", n, c)


def wf4():
    n = [node("Manual ou cron", "manualTrigger", {}, [0, 0], 1),
         http("POST /logistics/plan", "POST", "/logistics/plan", [260, 0],
              '={"producer_id": 2, "destination_id": "coop"}'),
         node("Texto da saída", "set", {"assignments": {"assignments": [
             {"name": "phone", "value": "+5500900000002", "type": "string"},
             {"name": "channel", "value": "whatsapp", "type": "string"},
             {"name": "text", "value": "={{$json.text}}", "type": "string"}]}}, [520, 0], 3.4),
         *send_nodes(780, 0), erro([260, 200])]
    c = wire(("Manual ou cron", "POST /logistics/plan", 0), ("POST /logistics/plan", "Texto da saída", 0),
             ("POST /logistics/plan", "Avisar equipe (erro)", 1), ("Texto da saída", "Canal", 0),
             ("Canal", "Enviar WhatsApp (Meta Cloud API)", 0), ("Canal", "Enviar SMS (Twilio)", 1))
    return flow("BALK WF4 Escoamento (melhor saída)", n, c)


if __name__ == "__main__":
    for fname, f in (("wf1_entrada", wf1()), ("wf2_diario", wf2()), ("wf3_novo_produtor", wf3()), ("wf4_escoamento", wf4())):
        (OUT / f"{fname}.json").write_text(json.dumps(f, ensure_ascii=False, indent=2), encoding="utf-8")
        print("gerado", fname)
