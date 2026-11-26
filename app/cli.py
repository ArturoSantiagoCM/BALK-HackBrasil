"""Operação pela linha de comando: python -m app.cli <comando>

  check                      confere a configuração e as fontes externas (diz o que falta para rodar de verdade)
  backtest [saida.md]        geada e chuva: previsão de 1 dia antes contra a reanálise (Open-Meteo, precisa de internet)
  backup <arquivo>           cópia consistente do banco SQLite
  purge-reports              apaga relatórios expirados (e as imagens deles)
  export-producer <telefone> LGPD: tudo que guardamos de um produtor, em JSON
  delete-producer <telefone> LGPD: apaga o produtor e todos os dados dele
"""
import json
import shutil
import sys
from datetime import datetime

from app import config, db


def cmd_check() -> int:
    problems = config.production_problems()
    print(f"ambiente: {config.env()} | dados: {config.data_mode()} | motor: {config.engine_name()}")
    print(f"banco: {config.db_path()} | work: {config.work_root()} | url pública: {config.public_base_url()}")
    for k in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_TEMPLATE_NAME",
              "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "ANTHROPIC_API_KEY"):
        import os
        print(f"  {k:24s} {'definida' if os.getenv(k) else '-'}")
    try:
        import check_apis  # raiz do projeto
        print("\nFontes externas:")
        check_apis.main()
    except Exception as e:  # noqa: BLE001
        print(f"(check_apis indisponível: {e})")
    print("\nPendências para produção:" if problems else "\nSem pendências de configuração.")
    for p in problems:
        print(" -", p)
    return 1 if problems and config.is_production() else 0


def _find(phone: str):
    p = db.get_producer_by_phone(phone)
    if not p:
        print("produtor não encontrado")
    return p


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "check":
        return cmd_check()
    if cmd == "backtest":  # python -m app.cli backtest [saida.md]  (usa a internet; Open-Meteo, uso não comercial)
        from app import backtest
        res = backtest.run_backtest()
        md = backtest.to_markdown(res)
        if args:
            from pathlib import Path
            Path(args[0]).write_text(md, encoding="utf-8")
            print("relatório salvo em", args[0])
        print(md)
        return 0
    if cmd == "backup" and args:
        db.backup_to(args[0])
        print("backup salvo em", args[0])
        return 0
    if cmd == "purge-reports":
        n = db.purge_expired_reports()
        base = config.work_root()
        removed = 0
        if base.exists():
            for d in base.glob("*/report/*"):
                if d.is_dir() and db.get_report(d.name) is None:
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
        print(f"{n} relatórios expirados apagados do banco; {removed} pastas de imagens removidas")
        return 0
    if cmd == "export-producer" and args:
        p = _find(args[0])
        if not p:
            return 1
        out = {"produtor": p.model_dump(), "consentimentos": db.list_consents(p.phone),  # com finalidade, versão do texto, data e origem
               "contatos_sucessor": db.list_contacts(p.id), "alertas_enviados": db.get_alert_log(p.id),
               "mensagens_enviadas": db.list_messages(p.id, limit=1000), "ultima_analise": db.last_analysis(p.id),
               "exportado_em": datetime.now().isoformat(timespec="seconds")}
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    if cmd == "delete-producer" and args:
        p = _find(args[0])
        if not p:
            return 1
        print("apagado:", db.delete_producer(p.id))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
