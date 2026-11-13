"""Leitura das regras de negócio implementadas em Java (serviço Spring).

Uma regra é um método anotado com ``@RegraPolitica``. O fingerprint cobre os
atributos da anotação e o corpo do método normalizado (sem comentários e com
espaços colapsados): reformatar ou comentar não muda a marca; mudar lógica,
decisão, prioridade ou justificativa muda.

Os testes de conformidade compilam só o pacote ``politica`` (Java puro, sem
Spring) com ``javac`` e executam ``ExecutorConformidade``.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

POLICY_CLASS = "PoliticaReembolso.java"
RUNNER = "br.edu.ifpb.lis.reembolso.politica.ExecutorConformidade"

_ANNOT = re.compile(r"@RegraPolitica\s*\(", re.S)
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


@dataclass(frozen=True)
class JavaRule:
    id: str
    priority: int
    requirement_ids: tuple[str, ...]
    decision: str
    rationale: str
    method: str
    body: str      # corpo normalizado
    source: str    # anotação + método, como está no arquivo

    def view(self) -> dict[str, Any]:
        return {"id": self.id, "priority": self.priority,
                "requirement_ids": list(self.requirement_ids), "decision": self.decision,
                "rationale": self.rationale, "source": self.source}


def normalize(code: str) -> str:
    """Remove comentários e espaços que não separam identificadores."""
    flat = " ".join(_COMMENTS.sub(" ", code).split())
    return re.sub(r"\s*([^\w\s])\s*", r"\1", flat)


def _balanced(text: str, start: int, open_: str, close: str) -> int:
    """Índice logo após o fechamento correspondente a ``text[start] == open_``."""
    depth, i, in_str = 0, start, False
    while i < len(text):
        c = text[i]
        if c == '"' and text[i - 1] != "\\":
            in_str = not in_str
        elif not in_str:
            if c == open_:
                depth += 1
            elif c == close:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    raise ValueError("Delimitadores desbalanceados no código Java")


def _attr(args: str, name: str) -> str | None:
    m = re.search(rf"\b{name}\s*=\s*", args)
    if not m:
        return None
    rest = args[m.end():]
    if rest.startswith('"'):
        end = rest.index('"', 1)
        return rest[1:end]
    if rest.startswith("{"):
        return rest[: _balanced(rest, 0, "{", "}")]
    return re.match(r"[\w.]+", rest).group(0)


def parse_rules(java: str) -> list[JavaRule]:
    rules = []
    for m in _ANNOT.finditer(java):
        args_end = _balanced(java, m.end() - 1, "(", ")")
        args = java[m.end(): args_end - 1]
        brace = java.index("{", args_end)
        sig = java[args_end:brace]
        name = re.search(r"(\w+)\s*\(", sig).group(1)
        end = _balanced(java, brace, "{", "}")
        reqs = re.findall(r'"([^"]+)"', _attr(args, "requisitos") or "")
        decision = (_attr(args, "decisao") or "").split(".")[-1]
        rules.append(JavaRule(
            id=_attr(args, "id") or "", priority=int(_attr(args, "prioridade") or 0),
            requirement_ids=tuple(reqs), decision=decision,
            rationale=_attr(args, "justificativa") or "", method=name,
            body=normalize(java[brace:end]), source=java[m.start():end]))
    return rules


def policy_version(java: str) -> str | None:
    m = re.search(r'VERSAO\s*=\s*"([^"]*)"', java)
    return m.group(1) if m else None


def rule_fingerprint(rule: JavaRule) -> str:
    raw = json.dumps({"id": rule.id, "priority": rule.priority,
                      "requirement_ids": sorted(rule.requirement_ids), "decision": rule.decision,
                      "rationale": rule.rationale, "body": rule.body},
                     ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ------------------------------------------------------------ conformidade

_TSV_FIELDS = ("fraude_suspeita", "falha_origem", "cancelamento_cliente", "despachado",
               "cliente_premium", "horas_apos_despacho")
_cache: dict[str, dict[str, str]] = {}


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def run_cases(policy_dir: Path, policy_java: str, cases: list[dict[str, Any]]) -> dict[str, str]:
    """Compila o pacote ``politica`` (com ``policy_java`` no lugar da classe) e
    devolve {id do caso: decisão}. Resultados são memorizados por conteúdo."""
    if not shutil.which("javac"):
        raise RuntimeError("javac não encontrado: os testes de conformidade exigem um JDK 21")
    tsv = "\n".join("\t".join([c["id"]] + [_cell(c["facts"].get(f)) for f in _TSV_FIELDS])
                    for c in cases) + "\n"
    others = sorted(p for p in Path(policy_dir).glob("*.java") if p.name != POLICY_CLASS)
    key = hashlib.sha256((policy_java + tsv + "".join(p.read_text() for p in others))
                         .encode("utf-8")).hexdigest()
    if key in _cache:
        return _cache[key]
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        for p in others:
            shutil.copy(p, src / p.name)
        (src / POLICY_CLASS).write_text(policy_java, encoding="utf-8")
        out = Path(tmp) / "classes"
        comp = subprocess.run(["javac", "-encoding", "UTF-8", "-d", str(out),
                               *map(str, src.glob("*.java"))], capture_output=True, text=True)
        if comp.returncode != 0:
            raise RuntimeError("Falha de compilação:\n" + comp.stderr[-2000:])
        run = subprocess.run(["java", "-cp", str(out), RUNNER], input=tsv,
                             capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            raise RuntimeError("Falha na execução dos casos:\n" + run.stderr[-2000:])
    result = {}
    for line in run.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            result[parts[0]] = parts[1]
    _cache[key] = result
    return result
