"""Artefatos de uma versão da API e verificação em níveis (L0-L4).

Um *bundle* reúne quatro artefatos que precisam coevoluir:

* ``spec``: especificação versionada (requisitos, índice de regras, digests);
* ``contract``: contrato OpenAPI; cada tag documenta uma parte da política e
  guarda, em ``x-apidrift``, o fingerprint das regras Java que descreve;
* ``java``: código-fonte da classe de política do serviço Spring;
* ``tests``: casos de conformidade com a decisão esperada.

Níveis (cumulativos):

* L1 versionamento convencional (versão declarada em cada artefato);
* L2 L1 + práticas usuais de API: esquema do contrato x código e testes de
  conformidade;
* L3 L2 + rastreabilidade SDD: IDs, referências, fingerprints do código no
  contrato, digests do texto do contrato na especificação e cobertura;
* L4 L3 + verificação semântica por LLM (``apiflow.semantic``).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

from .core import Issue
from . import java as J

CATEGORIES = ("estrutura", "versao", "esquema", "conformidade", "ids", "referencias",
              "fingerprint", "digest", "cobertura")
LEVELS: dict[str, frozenset[str]] = {
    "L0_sem_verificacao": frozenset(),
    "L1_versao": frozenset({"estrutura", "versao"}),
    "L2_testes_contrato": frozenset({"estrutura", "versao", "esquema", "conformidade"}),
    "L3_sdd": frozenset(CATEGORIES),
}
FULL = LEVELS["L3_sdd"]

CAMEL = {"fraude_suspeita": "fraudeSuspeita", "falha_origem": "falhaOrigem",
         "cancelamento_cliente": "cancelamentoCliente", "despachado": "despachado",
         "cliente_premium": "clientePremium", "horas_apos_despacho": "horasAposDespacho"}
SNAKE = {v: k for k, v in CAMEL.items()}
API_ROOT = "api"


# ------------------------------------------------------------------ E/S

def api_dir(root: Path) -> Path:
    return Path(root) / API_ROOT


def policy_dir(root: Path) -> Path:
    return api_dir(root) / "service/src/main/java/br/edu/ifpb/lis/reembolso/politica"


def load_bundle(root: Path, version: str = "v2", contract_version: str | None = None
                ) -> dict[str, Any]:
    base = api_dir(root)
    spec = yaml.safe_load((base / "spec" / version / "specification.yaml").read_text("utf-8"))
    contract = yaml.safe_load((base / "contracts" / (contract_version or version) /
                               "openapi.yaml").read_text("utf-8"))
    java = (policy_dir(root) / J.POLICY_CLASS).read_text("utf-8")
    tests = json.loads((base / "service/src/test/resources/casos-conformidade.json")
                       .read_text("utf-8"))
    return {"spec": spec, "contract": contract, "java": java, "tests": tests}


def tests_as_cases(tests: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": c["id"], "facts": {SNAKE[k]: v for k, v in c["solicitacao"].items()},
             "expected": c["esperado"]} for c in tests.get("casos", [])]


# ------------------------------------------------------------- marcas

def section_digest(tag: dict[str, Any]) -> str:
    raw = json.dumps({"name": tag.get("name"), "description": tag.get("description")},
                     ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tags(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in contract.get("tags") or [] if isinstance(t, dict)]


def synchronize(bundle: dict[str, Any]) -> dict[str, Any]:
    """Recalcula fingerprints e digests. Só deve ser usado após revisão humana."""
    b = copy.deepcopy(bundle)
    rules = {r.id: r for r in J.parse_rules(b["java"])}
    by_tag: dict[str, list[str]] = {}
    for r in b["spec"].get("rules", []):
        by_tag.setdefault(r.get("documented_in"), []).append(r["id"])
    for t in tags(b["contract"]):
        x = t.setdefault("x-apidrift", {})
        x["rule_fingerprints"] = {rid: J.rule_fingerprint(rules[rid])
                                  for rid in by_tag.get(t["name"], []) if rid in rules}
    b["spec"]["contract_digests"] = {t["name"]: section_digest(t) for t in tags(b["contract"])}
    return b


# ---------------------------------------------------------- verificação

def _java_record_fields(java_dir_files: dict[str, str]) -> list[str]:
    src = java_dir_files.get("Solicitacao.java", "")
    m = re.search(r"record\s+Solicitacao\s*\((.*?)\)\s*\{", src, re.S)
    return re.findall(r"\b(\w+)\s*(?:,|$)", " ".join(m.group(1).split())) if m else []


def _java_enum(java_dir_files: dict[str, str]) -> list[str]:
    m = re.search(r"enum\s+Decisao\s*\{([^}]*)\}", java_dir_files.get("Decisao.java", ""))
    return [v.strip() for v in m.group(1).split(",") if v.strip()] if m else []


def check(bundle: dict[str, Any], root: Path, categories: Iterable[str] = FULL) -> list[Issue]:
    enabled = set(categories)
    if not enabled:
        return []
    issues: list[Issue] = []

    def add(cat: str, msg: str) -> None:
        if cat in enabled:
            issues.append(Issue(cat, msg))

    spec, contract, java, tests = (bundle.get(k) for k in ("spec", "contract", "java", "tests"))
    try:
        rules_java = J.parse_rules(java or "")
    except (ValueError, AttributeError) as exc:
        return [Issue("estrutura", f"Código Java ilegível: {exc}")]
    if (not isinstance(spec, dict) or not isinstance(contract, dict) or not rules_java
            or not isinstance(spec.get("rules"), list) or not tags(contract)):
        return [Issue("estrutura", "Especificação, contrato ou código sem a estrutura esperada")]

    version = str(spec.get("version", ""))
    # versão declarada em cada artefato
    for label, v in (("do contrato", (contract.get("info") or {}).get("version")),
                     ("do código", J.policy_version(java)),
                     ("dos testes", (tests or {}).get("versao_politica"))):
        if str(v) != version:
            add("versao", f"Versão {label} ({v}) difere da especificação ({version})")
    for t in tags(contract):
        pv = (t.get("x-apidrift") or {}).get("policy-version")
        if str(pv) != version:
            add("versao", f"Seção '{t.get('name')}' do contrato na versão {pv}")

    # esquema: contrato OpenAPI x tipos Java
    files = {p.name: p.read_text("utf-8") for p in policy_dir(root).glob("*.java")}
    schemas = (contract.get("components") or {}).get("schemas") or {}
    props = set(((schemas.get("Solicitacao") or {}).get("properties") or {}))
    fields = set(_java_record_fields(files))
    if props != fields:
        add("esquema", f"Campos de Solicitacao divergem (contrato {sorted(props - fields)}, "
                       f"código {sorted(fields - props)})")
    enum = (((schemas.get("Resultado") or {}).get("properties") or {}).get("decisao") or {}).get("enum")
    if sorted(enum or []) != sorted(_java_enum(files)):
        add("esquema", "Valores de 'decisao' no contrato divergem do enum Decisao")

    # conformidade: casos esperados x execução do código
    if "conformidade" in enabled:
        cases = tests_as_cases(tests or {})
        try:
            got = J.run_cases(policy_dir(root), java, cases)
        except RuntimeError as exc:
            add("conformidade", f"Testes não executaram: {exc}")
        else:
            for c in cases:
                if got.get(c["id"]) != c["expected"]:
                    add("conformidade", f"{c['id']}: esperado {c['expected']}, obtido {got.get(c['id'])}")

    # ids
    reqs = spec.get("requirements") or []
    req_ids = [q.get("id") for q in reqs]
    spec_rule_ids = [r.get("id") for r in spec["rules"]]
    java_ids = [r.id for r in rules_java]
    tag_names = [t.get("name") for t in tags(contract)]
    for label, ids in (("requisitos", req_ids), ("regras da especificação", spec_rule_ids),
                       ("regras no código", java_ids), ("seções do contrato", tag_names)):
        if len(ids) != len(set(ids)) or None in ids:
            add("ids", f"IDs ausentes ou duplicados em {label}")

    # referências: especificação x código x contrato
    by_java = {r.id: r for r in rules_java}
    by_tag = {t.get("name"): t for t in tags(contract)}
    for rid in sorted(set(spec_rule_ids) - set(java_ids)):
        add("referencias", f"{rid}: regra especificada não existe no código")
    for rid in sorted(set(java_ids) - set(spec_rule_ids)):
        add("referencias", f"{rid}: regra no código ausente da especificação")
    documented: dict[str, set[str]] = {n: set() for n in by_tag}
    implemented: set[str] = set()
    for r in spec["rules"]:
        rid, jr = r.get("id"), by_java.get(r.get("id"))
        rq = list(r.get("requirement_ids") or [])
        if not rq or any(q not in req_ids for q in rq):
            add("referencias", f"{rid}: requisito inexistente")
        if jr is not None:
            implemented.update(jr.requirement_ids)
            if (jr.priority, jr.decision, sorted(jr.requirement_ids)) != (
                    r.get("priority"), r.get("decision"), sorted(rq)):
                add("referencias", f"{rid}: prioridade, decisão ou requisitos divergem do código")
        tag = by_tag.get(r.get("documented_in"))
        if tag is None:
            add("referencias", f"{rid}: seção do contrato inexistente ({r.get('documented_in')})")
            continue
        documented[tag["name"]].add(rid)
        fp = ((tag.get("x-apidrift") or {}).get("rule_fingerprints") or {}).get(rid)
        if jr is not None and fp != J.rule_fingerprint(jr):
            add("fingerprint", f"{rid}: código mudou sem revisão da seção '{tag['name']}'")
        if not set(rq).issubset(set((tag.get("x-apidrift") or {}).get("requirement_ids") or [])):
            add("referencias", f"{rid}: rastreabilidade incompleta na seção '{tag['name']}'")
    for name, tag in by_tag.items():
        listed = set(((tag.get("x-apidrift") or {}).get("rule_fingerprints") or {}))
        if listed != documented[name]:
            add("referencias", f"Seção '{name}' descreve regras {sorted(listed)}, "
                               f"especificação liga {sorted(documented[name])}")
        if not documented[name]:
            add("cobertura", f"Seção '{name}' não sustenta nenhuma regra")
        unknown = set((tag.get("x-apidrift") or {}).get("requirement_ids") or []) - set(req_ids)
        if unknown:
            add("referencias", f"Seção '{name}' cita requisitos inexistentes {sorted(unknown)}")

    # digests do texto do contrato fixados na especificação
    pinned = spec.get("contract_digests") or {}
    for name, tag in by_tag.items():
        if name not in pinned:
            add("digest", f"Texto da seção '{name}' não fixado na especificação")
        elif pinned[name] != section_digest(tag):
            add("digest", f"Texto da seção '{name}' alterado sem revisão da especificação")

    for q in req_ids:
        if q not in implemented:
            add("cobertura", f"{q}: requisito sem regra implementada no código")

    return sorted(set(issues), key=lambda i: (i.category, i.message))
