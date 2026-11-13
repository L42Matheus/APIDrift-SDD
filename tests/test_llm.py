"""Testes offline dos clientes de LLM, do cache e da CLI: sem rede e sem chave."""
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from apidrift import bundle as B
from apidrift.cli import main
from apidrift.core import find_root
from apidrift.llm import (DEFAULT_MODEL, FALLBACK_BETA, AnthropicClient, CachedLLM, FakeLLM,
                          LLMError, OpenAIClient)
from apidrift.semantic import ApiSemanticVerifier

ROOT = find_root(Path(__file__).resolve().parents[1])
BASE = B.load_bundle(ROOT, "v2")
OK = {"consistente": True, "divergencias": []}


def _run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["--root", str(ROOT), *argv])
    return code, json.loads(out.getvalue())


class CacheTests(unittest.TestCase):
    def test_cache_round_trip_and_offline_miss(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            fake = FakeLLM(lambda s, u: OK, model=DEFAULT_MODEL)
            ApiSemanticVerifier(CachedLLM(fake, path)).check(BASE)
            offline = CachedLLM(None, path, offline=True)
            self.assertEqual(ApiSemanticVerifier(offline).check(BASE), [])
            n = len(B.tags(BASE["contract"]))
            self.assertEqual((offline.hits, offline.misses), (n, 0))
            with self.assertRaises(LLMError):
                offline.complete_json("s", "pedido novo", {})

    def test_published_caches_reproduce_the_paper(self):
        for provider, cache in (("anthropic", "claude.json"), ("openai", "gpt.json")):
            code, out = _run(["semantic-check", "--provider", provider, "--offline",
                              "--cache", str(ROOT / "llm_cache" / cache)])
            self.assertNotIn("indisponível", json.dumps(out, ensure_ascii=False), provider)
            self.assertEqual(code, 0 if provider == "anthropic" else 2)


class CliTests(unittest.TestCase):
    def test_validate_v2_is_consistent(self):
        code, out = _run(["validate", "--level", "L1_versao"])
        self.assertEqual((code, out["valid"]), (0, True))

    def test_validate_stale_contract_fails(self):
        code, out = _run(["validate", "--contract-version", "v1", "--level", "L1_versao"])
        self.assertEqual(code, 2)
        self.assertTrue(any("versao" in e for e in out["errors"]))

    def test_fingerprint_matches_committed_marks(self):
        code, out = _run(["fingerprint"])
        self.assertEqual(code, 0)
        self.assertEqual(out["contract_digests"], BASE["spec"]["contract_digests"])


class ClientWiringTests(unittest.TestCase):
    """Confere os parâmetros enviados aos SDKs, com clientes simulados."""

    @unittest.skipUnless(importlib.util.find_spec("anthropic"), "SDK anthropic ausente")
    def test_anthropic_request_and_refusal(self):
        sent = {}

        def create(**kw):
            sent.update(kw)
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text='{"ok": true}')])
        fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
        client = AnthropicClient(client=fake)
        self.assertEqual(client.complete_json("s", "u", {"type": "object"}), {"ok": True})
        self.assertEqual(sent["model"], DEFAULT_MODEL)
        self.assertEqual(sent["fallbacks"], "default")
        self.assertIn(FALLBACK_BETA, sent["betas"])
        self.assertEqual(sent["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("temperature", sent)

        fake.beta.messages.create = lambda **kw: SimpleNamespace(stop_reason="refusal", content=[])
        with self.assertRaises(LLMError):
            client.complete_json("s", "u", {})

    @unittest.skipUnless(importlib.util.find_spec("openai"), "SDK openai ausente")
    def test_openai_request_and_refusal(self):
        sent = {}

        def create(**kw):
            sent.update(kw)
            return SimpleNamespace(status="completed", output=[], output_text='{"ok": 1}')
        fake = SimpleNamespace(responses=SimpleNamespace(create=create))
        client = OpenAIClient(client=fake)
        self.assertEqual(client.complete_json("s", "u", {"type": "object"}), {"ok": 1})
        self.assertTrue(sent["text"]["format"]["strict"])
        self.assertFalse(sent["store"])

        refusal = SimpleNamespace(content=[SimpleNamespace(type="refusal", refusal="não")])
        fake.responses.create = lambda **kw: SimpleNamespace(
            status="completed", output=[refusal], output_text="")
        with self.assertRaises(LLMError):
            client.complete_json("s", "u", {})


if __name__ == "__main__":
    unittest.main()
