"""Tipos comuns e localização da raiz do repositório."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "APIDRIFT_ROOT"


@dataclass(frozen=True, order=True)
class Issue:
    category: str
    message: str

    def __str__(self) -> str:
        return f"[{self.category}] {self.message}"


def _is_root(p: Path) -> bool:
    return (p / "api" / "spec").is_dir() and (p / "api" / "contracts").is_dir()


def find_root(explicit: str | Path | None = None) -> Path:
    """Raiz com ``api/spec`` e ``api/contracts``: argumento, variável de ambiente ou busca."""
    if explicit:
        p = Path(explicit).resolve()
        if not _is_root(p):
            raise FileNotFoundError(f"{p} não contém api/spec e api/contracts")
        return p
    env = os.environ.get(ENV_VAR)
    if env:
        return find_root(env)
    for start in (Path.cwd().resolve(), Path(__file__).resolve().parent):
        for p in (start, *start.parents):
            if _is_root(p):
                return p
    raise FileNotFoundError("Artefatos não encontrados: execute dentro do repositório, "
                            f"use --root ou defina {ENV_VAR}.")


def versions(root: Path) -> list[str]:
    return sorted(p.name for p in (Path(root) / "api" / "spec").iterdir() if p.is_dir())
