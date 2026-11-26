"""Configuração: variáveis de ambiente e arquivos YAML (lidos a cada chamada de função)."""
import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def data_mode() -> str:
    """simulado = só dados fixos; real = APIs; auto = tenta real, cai para simulado."""
    return os.getenv("DATA_MODE", "auto").lower()


def engine_name() -> str:
    return os.getenv("ENGINE", "python").lower()


def work_root() -> Path:
    return Path(os.getenv("BALK_WORK", ROOT / "work"))


def db_path() -> Path:
    return Path(os.getenv("BALK_DB", ROOT / "balk.db"))


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def rules() -> dict:
    return load_yaml("rules.yaml")


def crops_cfg() -> dict:
    return load_yaml("crops.yaml")
