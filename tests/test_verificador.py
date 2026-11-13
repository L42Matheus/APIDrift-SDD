"""Testes offline do verificador (especificação x OpenAPI x código Java).

Os testes que executam o código Java exigem ``javac``; sem JDK eles são pulados.
"""
import copy
import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from apidrift import bundle as B
from apidrift import java as J
from apidrift.mutations import MUTATIONS, apply, run_api_mutation_study
from apidrift.semantic import ApiSemanticVerifier
from apidrift.llm import FakeLLM, LLMError
from apidrift.core import find_root

ROOT = find_root(Path(__file__).resolve().parents[1])
HAS_JDK = shutil.which("javac") is not None
BASE = B.load_bundle(ROOT, "v2")
STALE = B.load_bundle(ROOT, "v2", "v1")["contract"]
STRUCTURAL = B.FULL - {"conformidade"}


def _cats(issues):
    return {i.category for i in issues}


class JavaParsingTest(unittest.TestCase):
    def test_rules_are_parsed_with_annotation_attributes(self):
        rules = {r.id: r for r in J.parse_rules(BASE["java"])}
        self.assertEqual(set(rules), {"REG-SEG", "REG-FALHA", "REG-PREMIUM-EXC",
                                      "REG-CANCEL-ENVIADO", "REG-CANCEL-PRE"})
        premium = rules["REG-PREMIUM-EXC"]
        self.assertEqual(premium.priority, 25)
        self.assertEqual(premium.decision, "PERMITIR")
        self.assertIn("REQ-05", premium.requirement_ids)
        self.assertIn("horasAposDespacho", premium.body)
        self.assertEqual(J.policy_version(BASE["java"]), "2")

    def test_fingerprint_ignores_comments_and_whitespace(self):
        java = BASE["java"].replace("return Boolean.TRUE.equals(s.fraudeSuspeita());",
                                    "// comentário\n        return Boolean.TRUE.equals(  s.fraudeSuspeita()  );")
        before = {r.id: J.rule_fingerprint(r) for r in J.parse_rules(BASE["java"])}
        after = {r.id: J.rule_fingerprint(r) for r in J.parse_rules(java)}
        self.assertEqual(before, after)

    def test_fingerprint_changes_with_logic(self):
        java = BASE["java"].replace("s.horasAposDespacho() <= 1.0", "s.horasAposDespacho() <= 2.0")
        before = {r.id: J.rule_fingerprint(r) for r in J.parse_rules(BASE["java"])}
        after = {r.id: J.rule_fingerprint(r) for r in J.parse_rules(java)}
        self.assertNotEqual(before["REG-PREMIUM-EXC"], after["REG-PREMIUM-EXC"])
        self.assertEqual(before["REG-SEG"], after["REG-SEG"])

    def test_unbalanced_code_raises(self):
        with self.assertRaises(ValueError):
            J.parse_rules('@RegraPolitica(id = "X"')


class StructuralCheckTest(unittest.TestCase):
    def test_synchronized_v2_is_clean(self):
        self.assertEqual(B.check(BASE, ROOT, STRUCTURAL), [])

    def test_levels_are_cumulative(self):
        self.assertEqual(B.check(BASE, ROOT, B.LEVELS["L0_sem_verificacao"]), [])
        names = list(B.LEVELS)
        for lower, upper in zip(names, names[1:]):
            self.assertTrue(B.LEVELS[lower] <= B.LEVELS[upper])

    def test_partial_update_is_a_version_issue(self):
        m = next(m for m in MUTATIONS if m.id == "M08")
        issues = B.check(apply(m, BASE, STALE), ROOT, STRUCTURAL)
        self.assertEqual(_cats(issues), {"versao"})

    def test_code_change_breaks_fingerprint(self):
        m = next(m for m in MUTATIONS if m.id == "M01")
        self.assertIn("fingerprint", _cats(B.check(apply(m, BASE, STALE), ROOT, STRUCTURAL)))

    def test_edited_contract_text_breaks_digest(self):
        m = next(m for m in MUTATIONS if m.id == "M09")
        self.assertIn("digest", _cats(B.check(apply(m, BASE, STALE), ROOT, STRUCTURAL)))

    def test_resynchronized_drift_escapes_structure(self):
        for mid in ("M10", "M11"):
            m = next(m for m in MUTATIONS if m.id == mid)
            self.assertEqual(B.check(apply(m, BASE, STALE), ROOT, STRUCTURAL), [], mid)

    def test_orphan_requirement_is_coverage_issue(self):
        m = next(m for m in MUTATIONS if m.id == "M06")
        self.assertIn("cobertura", _cats(B.check(apply(m, BASE, STALE), ROOT, STRUCTURAL)))

    def test_schema_mismatch(self):
        b = copy.deepcopy(BASE)
        del b["contract"]["components"]["schemas"]["Solicitacao"]["properties"]["clientePremium"]
        self.assertIn("esquema", _cats(B.check(b, ROOT, STRUCTURAL)))

    def test_broken_structure(self):
        b = copy.deepcopy(BASE)
        b["contract"]["tags"] = []
        self.assertEqual(_cats(B.check(b, ROOT)), {"estrutura"})

    def test_benign_operators_mostly_pass_structure(self):
        for mid in ("N01", "N02", "N03", "N04", "N06"):
            m = next(m for m in MUTATIONS if m.id == mid)
            self.assertEqual(B.check(apply(m, BASE, STALE), ROOT, STRUCTURAL), [], mid)


@unittest.skipUnless(HAS_JDK, "javac indisponível")
class ConformanceTest(unittest.TestCase):
    def test_labeled_cases_pass_on_v2(self):
        self.assertEqual(B.check(BASE, ROOT, {"conformidade"}), [])

    def test_threshold_change_fails_case(self):
        m = next(m for m in MUTATIONS if m.id == "M01")
        issues = B.check(apply(m, BASE, STALE), ROOT, {"conformidade"})
        self.assertTrue(any(i.message.startswith("C07") for i in issues))

    def test_mutation_study_without_llm(self):
        with TemporaryDirectory() as tmp:
            result = run_api_mutation_study(ROOT, output_dir=Path(tmp))
            self.assertTrue((Path(tmp) / "api_mutation_summary.csv").exists())
        levels = {r["level"]: r for r in result["levels"]}
        self.assertEqual(levels["L0_sem_verificacao"]["tp"], 0)
        self.assertEqual(levels["L3_sdd"]["missed"], "M10|M11")
        self.assertGreater(levels["L3_sdd"]["sensitivity"], levels["L2_testes_contrato"]["sensitivity"])


def _semantic_responder(system, user):
    payload = json.loads(user[user.index("{"):])
    text = payload["secao_do_contrato"]["descricao"] or ""
    sources = " ".join(r["source"] for r in payload["metodos_java_documentados_nesta_secao"])
    ok = not ("sempre negado" in text and "excecaoPremium" in sources) and "<= 2.0" not in sources
    return {"consistente": ok, "divergencias": [] if ok else [
        {"regra_id": "REG-PREMIUM-EXC", "aspecto": "limiar", "explicacao": "texto e código divergem"}]}


class ApiSemanticTest(unittest.TestCase):
    def test_one_prompt_per_documented_section(self):
        llm = FakeLLM(_semantic_responder)
        self.assertEqual(ApiSemanticVerifier(llm).check(BASE), [])
        self.assertEqual(len(llm.calls), len(B.tags(BASE["contract"])))
        self.assertIn("REG-PREMIUM-EXC", llm.calls[-1][1] + llm.calls[0][1] + llm.calls[1][1])

    def test_resynchronized_text_drift_is_flagged(self):
        m = next(m for m in MUTATIONS if m.id == "M10")
        issues = ApiSemanticVerifier(FakeLLM(_semantic_responder)).check(apply(m, BASE, STALE))
        self.assertEqual(_cats(issues), {"semantica"})
        self.assertTrue(any("REG-PREMIUM-EXC" in i.message for i in issues))

    def test_failure_is_fail_closed(self):
        def boom(system, user):
            raise LLMError("sem rede")
        verifier = ApiSemanticVerifier(FakeLLM(boom))
        issues = verifier.check(BASE)
        self.assertEqual(len(issues), len(B.tags(BASE["contract"])))
        self.assertTrue(all("indisponível" in i.message for i in issues))
        self.assertTrue(all("error" in r for r in verifier.last_report))

    def test_out_of_schema_answer_is_fail_closed(self):
        verifier = ApiSemanticVerifier(FakeLLM(lambda s, u: {"consistente": "sim"}))
        self.assertTrue(all("indisponível" in i.message for i in verifier.check(BASE)))

    def test_inconsistent_without_details(self):
        verifier = ApiSemanticVerifier(FakeLLM(lambda s, u: {"consistente": False, "divergencias": []}))
        self.assertTrue(all("não detalhada" in i.message for i in verifier.check(BASE)))

    def test_unreadable_java(self):
        b = copy.deepcopy(BASE)
        b["java"] = '@RegraPolitica(id = "X"'
        issues = ApiSemanticVerifier(FakeLLM(_semantic_responder)).check(b)
        self.assertEqual(len(issues), 1)


if __name__ == "__main__":
    unittest.main()
