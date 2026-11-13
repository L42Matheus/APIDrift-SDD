"""Estudo de mutações sobre a API: especificação x contrato OpenAPI x código Java.

Cada operador parte da versão 2 sincronizada e altera um ou mais artefatos.
``drift=True``: os artefatos passam a divergir em significado (deveria
alertar). ``drift=False``: mudança benigna ou evolução completa (não deveria).

Métrica operacional: se a deriva não é detectada, a versão seria liberada; conta
quantos dos 18 casos a API passaria a decidir de forma diferente da política
vigente (``decisoes_erradas_liberadas``).
"""
from __future__ import annotations

import copy
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import bundle as B
from . import java as J

Bundle = dict[str, Any]


def _sub(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Trecho não encontrado exatamente uma vez: {old[:60]!r}")
    return text.replace(old, new)


def _tag(b: Bundle, name: str) -> dict:
    return next(t for t in b["contract"]["tags"] if t["name"] == name)


def _case(b: Bundle, cid: str) -> dict:
    return next(c for c in b["tests"]["casos"] if c["id"] == cid)


THRESHOLD = "s.horasAposDespacho() <= 1.0"


def m01_limiar_codigo(b):
    b["java"] = _sub(b["java"], THRESHOLD, "s.horasAposDespacho() <= 2.0")
    return b


def m02_precedencia(b):
    b["java"] = _sub(b["java"], 'id = "REG-PREMIUM-EXC", prioridade = 25',
                     'id = "REG-PREMIUM-EXC", prioridade = 35')
    return b


def m03_decisao(b):
    b["java"] = _sub(b["java"], 'requisitos = {"REQ-04"},\n            decisao = Decisao.PERMITIR',
                     'requisitos = {"REQ-04"},\n            decisao = Decisao.NEGAR')
    return b


def m04_regra_removida(b):
    start = b["java"].index('    @RegraPolitica(id = "REG-PREMIUM-EXC"')
    end = b["java"].index('    @RegraPolitica(id = "REG-CANCEL-ENVIADO"')
    b["java"] = b["java"][:start] + b["java"][end:]
    return b


def m05_requisito_removido(b):
    b["spec"]["requirements"] = [q for q in b["spec"]["requirements"] if q["id"] != "REQ-05"]
    return b


def m06_requisito_orfao(b):
    b["spec"]["requirements"].append({
        "id": "REQ-06", "description": "Cliente premium com atraso superior a 2 horas recebe reembolso.",
        "acceptance_criterion": "Premium e atraso > 2h, sem fraude: PERMITIR."})
    return b


def m07_justificativa(b):
    b["java"] = _sub(b["java"], '"Exceção premium: pedido cancelado até 1 hora após despacho."',
                     '"Exceção premium: pedido cancelado até 2 horas após despacho."')
    return b


def m08_atualizacao_parcial(b):
    _tag(b, "antifraude")["x-apidrift"]["policy-version"] = "1"
    return b


def m09_texto_editado(b):
    _tag(b, "cancelamento")["description"] = (
        "Cancelamento antes do despacho é permitido. Após despacho, é sempre negado.")
    return b


def m10_texto_invertido_ressincronizado(b):
    return B.synchronize(m09_texto_editado(b))


def m11_codigo_e_testes_alterados_ressincronizados(b):
    b = m01_limiar_codigo(b)
    _case(b, "C07")["esperado"] = "PERMITIR"   # o desenvolvedor "conserta" o teste
    return B.synchronize(b)


def m12_contrato_antigo(b, *, stale: dict | None = None):
    b["contract"] = copy.deepcopy(stale)
    return b


def n01_reordenar_metodos(b):
    start = b["java"].index('    @RegraPolitica(id = "REG-SEG"')
    mid = b["java"].index('    @RegraPolitica(id = "REG-FALHA"')
    end = b["java"].index('    @RegraPolitica(id = "REG-PREMIUM-EXC"')
    b["java"] = b["java"][:start] + b["java"][mid:end] + b["java"][start:mid] + b["java"][end:]
    return b


def n02_reordenar_secoes(b):
    b["contract"]["tags"] = list(reversed(b["contract"]["tags"]))
    return b


def n03_comentarios_formatacao(b):
    b["java"] = _sub(b["java"], "        return Boolean.TRUE.equals(s.fraudeSuspeita());",
                     "        // sinal vindo do serviço antifraude\n"
                     "        return Boolean.TRUE.equals(  s.fraudeSuspeita()  );")
    return b


def n04_metadados(b):
    b["contract"]["info"]["contact"] = {"name": "Equipe de Pagamentos"}
    b["contract"]["servers"] = [{"url": "https://api.exemplo.test"}]
    return b


def n05_correcao_pontuacao(b):
    t = _tag(b, "falhas-operacionais")
    t["description"] = _sub(t["description"], "transportadora gera", "transportadora, gera")
    return b


def n06_evolucao_sincronizada(b):
    b = m01_limiar_codigo(b)
    b["java"] = _sub(b["java"], '"Exceção premium: pedido cancelado até 1 hora após despacho."',
                     '"Exceção premium: pedido cancelado até 2 horas após despacho."')
    _case(b, "C07")["esperado"] = "PERMITIR"
    t = _tag(b, "cancelamento")
    t["description"] = _sub(t["description"], "até 1 hora", "até 2 horas")
    q = next(q for q in b["spec"]["requirements"] if q["id"] == "REQ-05")
    q["acceptance_criterion"] = _sub(q["acceptance_criterion"], "até 1 hora", "até 2 horas")
    return B.synchronize(b)


def n07_refatoracao_renomeia_parametro(b):
    start = b["java"].index("    boolean excecaoPremium(Solicitacao s) {")
    end = b["java"].index("    @RegraPolitica", start)
    method = b["java"][start:end].replace("Solicitacao s)", "Solicitacao solicitacao)") \
                                 .replace("s.", "solicitacao.")
    b["java"] = b["java"][:start] + method + b["java"][end:]
    return b


@dataclass(frozen=True)
class Mutation:
    id: str
    artifact: str
    description: str
    drift: bool
    operator: Callable[..., Bundle]


MUTATIONS: list[Mutation] = [
    Mutation("M01", "código", "Limiar da exceção premium muda (1h->2h) só no código", True, m01_limiar_codigo),
    Mutation("M02", "código", "Prioridade da exceção premium alterada (perde para a regra geral)", True, m02_precedencia),
    Mutation("M03", "código", "Decisão invertida em REG-CANCEL-PRE", True, m03_decisao),
    Mutation("M04", "código", "Método da exceção premium removido; contrato ainda a descreve", True, m04_regra_removida),
    Mutation("M05", "especificação", "REQ-05 removido; código e contrato ainda o citam", True, m05_requisito_removido),
    Mutation("M06", "especificação", "Requisito novo sem regra implementada", True, m06_requisito_orfao),
    Mutation("M07", "código", "Justificativa devolvida pela API contradiz o contrato", True, m07_justificativa),
    Mutation("M08", "contrato", "Atualização parcial: seção antifraude ficou na versão 1", True, m08_atualizacao_parcial),
    Mutation("M09", "contrato", "Descrição de cancelamento perde a exceção, sem revisão", True, m09_texto_editado),
    Mutation("M10", "contrato", "Descrição perde a exceção e as marcas são recalculadas", True, m10_texto_invertido_ressincronizado),
    Mutation("M11", "código+testes", "Limiar muda no código, testes são ajustados e marcas recalculadas", True, m11_codigo_e_testes_alterados_ressincronizados),
    Mutation("M12", "contrato", "Contrato OpenAPI v1 inteiro com código v2", True, m12_contrato_antigo),
    Mutation("N01", "código", "Métodos de regra reordenados na classe", False, n01_reordenar_metodos),
    Mutation("N02", "contrato", "Seções (tags) reordenadas no contrato", False, n02_reordenar_secoes),
    Mutation("N03", "código", "Comentário e formatação no método de fraude", False, n03_comentarios_formatacao),
    Mutation("N04", "contrato", "Metadados do contrato (contato, servidores)", False, n04_metadados),
    Mutation("N05", "contrato", "Correção de pontuação na seção de falhas", False, n05_correcao_pontuacao),
    Mutation("N06", "todos", "Evolução completa e sincronizada (limiar 2h em código, testes, contrato e requisito)", False, n06_evolucao_sincronizada),
    Mutation("N07", "código", "Refatoração: parâmetro renomeado na exceção premium", False, n07_refatoracao_renomeia_parametro),
]


def apply(m: Mutation, base: Bundle, stale_contract: dict) -> Bundle:
    b = copy.deepcopy(base)
    if m.operator is m12_contrato_antigo:
        return m.operator(b, stale=stale_contract)
    return m.operator(b)


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def run_api_mutation_study(root: Path, verifier: Any = None, output_dir: Path | None = None,
                           prefix: str = "api_mutation") -> dict[str, Any]:
    base = B.load_bundle(root, "v2")
    stale = B.load_bundle(root, "v2", "v1")["contract"]
    oracle_cases = B.tests_as_cases(base["tests"])
    levels: dict[str, Any] = dict(B.LEVELS)
    if verifier is not None:
        levels["L4_semantica"] = "semantica"
    rows = []
    for m in MUTATIONS:
        mb = apply(m, base, stale)
        decided = J.run_cases(B.policy_dir(root), mb["java"], oracle_cases)
        expected = ({c["id"]: c["expected"] for c in oracle_cases} if m.drift else
                    {c["id"]: c["expected"] for c in B.tests_as_cases(mb["tests"])})
        wrong = sum(decided.get(cid) != e for cid, e in expected.items())
        semantic = verifier.check(mb) if verifier is not None else []
        for level, cats in levels.items():
            if cats == "semantica":
                issues = B.check(mb, root, B.FULL) + semantic
            else:
                issues = B.check(mb, root, cats)
            detected = bool(issues)
            rows.append({
                "mutation": m.id, "artifact": m.artifact, "drift": m.drift, "level": level,
                "detected": detected, "n_issues": len(issues),
                "categories": "|".join(sorted({i.category for i in issues})),
                "decisoes_divergentes": wrong,
                "decisoes_erradas_liberadas": wrong if (m.drift and not detected) else 0,
            })
    summary = []
    for level in levels:
        lr = [r for r in rows if r["level"] == level]
        tp = sum(r["detected"] and r["drift"] for r in lr)
        fn = sum(not r["detected"] and r["drift"] for r in lr)
        fp = sum(r["detected"] and not r["drift"] for r in lr)
        tn = sum(not r["detected"] and not r["drift"] for r in lr)
        summary.append({
            "level": level, "mutants": len(lr), "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "sensitivity": _rate(tp, tp + fn), "false_alarm_rate": _rate(fp, fp + tn),
            "missed": "|".join(r["mutation"] for r in lr if r["drift"] and not r["detected"]),
            "false_alarms": "|".join(r["mutation"] for r in lr if not r["drift"] and r["detected"]),
            "decisoes_erradas_liberadas": sum(r["decisoes_erradas_liberadas"] for r in lr),
        })
    protocol = "api-mutation-v0.1"
    if verifier is not None:
        protocol += f" ({getattr(verifier.llm, 'model', '?')})"
    result = {"protocol": protocol, "levels": summary, "observations": rows,
              "mutations": [{"id": m.id, "artifact": m.artifact, "drift": m.drift,
                             "description": m.description} for m in MUTATIONS]}
    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name, data in ((f"{prefix}_observations.csv", rows), (f"{prefix}_summary.csv", summary)):
            with open(out / name, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(data[0]))
                w.writeheader()
                w.writerows(data)
        with open(out / f"{prefix}_summary.json", "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in result.items() if k != "observations"}, f,
                      indent=2, ensure_ascii=False)
    return result
