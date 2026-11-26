# BALK: guia para o Claude Code

MVP do hackathon (entrega 30/11, 23h59 Brasília). Leia o README para a arquitetura.

- Python 3.12; rodar testes com `python -m pytest -q` (todos usam dados simulados e banco temporário).
- `app/models.py` é o contrato sagrado: mudar só com os 4 da equipe de acordo.
- Uma função por vez, com teste. Primeiro a versão simulada, depois a real.
- Limiares só em `rules.yaml`/`crops.yaml`, sempre com a fonte. O sistema orienta, não prescreve (sem produto, sem dose).
- Nunca versionar `.env` ou chaves. Nenhum dado pessoal real na demo.
- Guia completo: `docs/GUIA_PROGRAMADORES.md`. Motor espacial em `app/geo/` (nenhum código do QGIS no repositório: é GPL e o regulamento proíbe fork).
- Antes de submeter, rodar o agente `repo-publication-auditor` e o `security-auditor`.

Agentes em `.claude/agents/`: `fastapi-pro`, `python-pro`, `test-automator`, `debugger`, `backend-security-coder`
(do repositório wshobson/agents) e `data-scientist`, `security-auditor`, `repo-publication-auditor`, `technical-writer`
(do davila7/claude-code-templates).
