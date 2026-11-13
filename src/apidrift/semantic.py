"""L4: o LLM compara o código Java de cada regra com a descrição da
seção do contrato OpenAPI que a documenta e com os requisitos ligados.

Um pedido por seção do contrato, saída em esquema JSON fixo e política
fail-closed: falha ou recusa do modelo vira alerta, nunca aprovação.
"""
from __future__ import annotations

import json
from typing import Any

from .core import Issue
from .llm import LLMClient, LLMError
from . import bundle as B
from . import java as J

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "consistente": {"type": "boolean"},
        "divergencias": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "regra_id": {"type": "string"},
                    "aspecto": {"type": "string",
                                "enum": ["limiar", "decisao", "condicao", "excecao",
                                         "precedencia", "requisito", "outro"]},
                    "explicacao": {"type": "string"},
                },
                "required": ["regra_id", "aspecto", "explicacao"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["consistente", "divergencias"],
    "additionalProperties": False,
}

CATEGORY = "semantica"
PROMPT_VERSION = "api-semantic-v1"

SYSTEM = (
    "Você audita a coevolução entre o código de um serviço Spring (Java) e o contrato "
    "OpenAPI que o documenta. Compare o significado, não a redação: limiares, decisões, "
    "condições, exceções e precedência. Diferenças de pontuação, estilo, nomes de "
    "variáveis ou formatação não são divergências. Se o texto omite um detalhe que o "
    "código trata, só aponte divergência quando a omissão mudar a decisão para algum "
    "caso. Responda em português."
)


def build_prompt(tag: dict[str, Any], rules: list[J.JavaRule], requirements: list[dict[str, Any]],
                 all_rules: list[J.JavaRule]) -> str:
    payload = {
        "secao_do_contrato": {"tag": tag.get("name"),
                              "titulo": (tag.get("x-apidrift") or {}).get("title"),
                              "descricao": tag.get("description")},
        "metodos_java_documentados_nesta_secao": [r.view() for r in rules],
        "requisitos_ligados": [{k: q.get(k) for k in ("id", "description", "acceptance_criterion")}
                               for q in requirements],
        "todas_as_regras_por_prioridade": [
            {"id": r.id, "priority": r.priority, "decision": r.decision, "source": r.source}
            for r in sorted(all_rules, key=lambda r: (r.priority, r.id))],
    }
    return (
        "No serviço, as regras são avaliadas em ordem crescente de prioridade; a primeira cujo "
        "método devolve true decide, com a decisão e a justificativa da anotação @RegraPolitica. "
        "Uma exclusão citada no texto (ex.: fraude) está implementada se uma regra avaliada antes "
        "já decide esses casos.\n\n"
        "A descrição da seção do contrato e os requisitos descrevem o mesmo comportamento que o "
        "código executa? Liste cada divergência de significado.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )


class ApiSemanticVerifier:
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.last_report: list[dict[str, Any]] = []

    def check(self, bundle: dict[str, Any]) -> list[Issue]:
        spec, contract = bundle.get("spec") or {}, bundle.get("contract") or {}
        try:
            java_rules = J.parse_rules(bundle.get("java") or "")
        except (ValueError, AttributeError):
            return [Issue(CATEGORY, "Código Java ilegível para a verificação semântica")]
        by_id = {r.id: r for r in java_rules}
        reqs = {q.get("id"): q for q in spec.get("requirements") or [] if isinstance(q, dict)}
        issues: list[Issue] = []
        self.last_report = []
        for tag in B.tags(contract):
            name = tag.get("name")
            ids = [r.get("id") for r in spec.get("rules") or [] if r.get("documented_in") == name]
            documented = [by_id[i] for i in ids if i in by_id]
            if not documented:
                continue  # seção sem regra no código já é alerta estrutural (L3)
            req_ids = sorted({q for r in documented for q in r.requirement_ids}
                             | set((tag.get("x-apidrift") or {}).get("requirement_ids") or []))
            prompt = build_prompt(tag, documented, [reqs[q] for q in req_ids if q in reqs], java_rules)
            try:
                answer = self.llm.complete_json(SYSTEM, prompt, SCHEMA)
                consistent, divergences = answer["consistente"], answer.get("divergencias") or []
                if not isinstance(consistent, bool) or not isinstance(divergences, list):
                    raise LLMError("Resposta fora do esquema")
            except (LLMError, KeyError, TypeError) as exc:
                issues.append(Issue(CATEGORY, f"{name}: verificação semântica indisponível ({exc})"))
                self.last_report.append({"secao": name, "error": str(exc)})
                continue
            self.last_report.append({"secao": name, **answer})
            if not consistent and not divergences:
                issues.append(Issue(CATEGORY, f"{name}: divergência semântica não detalhada"))
            for d in divergences:
                issues.append(Issue(CATEGORY, f"{name}/{d.get('regra_id')}: "
                                              f"[{d.get('aspecto')}] {d.get('explicacao')}"))
        return sorted(set(issues), key=lambda i: i.message)
