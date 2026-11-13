"""Linha de comando do APIDrift-SDD.

Comandos: validate, fingerprint, semantic-check, mutate e demo.
As chaves de API vêm só do ambiente (ANTHROPIC_API_KEY / OPENAI_API_KEY).
Saída: 0 consistente, 2 divergências encontradas, 3 falha do LLM.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import bundle as B
from .core import find_root, versions
from .llm import PROVIDERS, LLMError, make_client
from .mutations import MUTATIONS, apply, run_api_mutation_study
from .semantic import ApiSemanticVerifier


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _llm_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("LLM")
    g.add_argument("--provider", choices=PROVIDERS, default="anthropic",
                   help="anthropic (Claude, padrão) ou openai (GPT)")
    g.add_argument("--model", default=None,
                   help="Padrão: claude-opus-5-5 / gpt-5.5 (ou APIDRIFT_MODEL)")
    g.add_argument("--effort", default=None, help="Esforço de raciocínio (padrão: medium)")
    g.add_argument("--cache", default=None,
                   help="Arquivo JSON de cache das respostas (reprodutibilidade)")
    g.add_argument("--offline", action="store_true",
                   help="Usa só o cache; nenhuma chamada de rede")


def _client(args):
    return make_client(args.provider, args.cache, args.offline, args.model, args.effort)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apidrift", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="Raiz do repositório (padrão: detecção automática)")
    commands = parser.add_subparsers(dest="command", required=True)

    v = commands.add_parser("validate", help="L1-L3: especificação x contrato OpenAPI x código Java")
    v.add_argument("--version", default="v2")
    v.add_argument("--contract-version", default=None, help="Padrão: igual à especificação")
    v.add_argument("--level", choices=list(B.LEVELS), default="L3_sdd")

    f = commands.add_parser("fingerprint", help="Recalcula as marcas do contrato (após revisão humana!)")
    f.add_argument("--version", default="v2")
    f.add_argument("--write", action="store_true", help="Grava as marcas na especificação e no contrato")

    s = commands.add_parser("semantic-check", help="L4: o LLM compara o texto do contrato e o código")
    s.add_argument("--version", default="v2")
    s.add_argument("--contract-version", default=None)
    _llm_args(s)

    m = commands.add_parser("mutate", help="Estudo de mutações (código, testes, contrato e especificação)")
    m.add_argument("--output", default=None, help="Padrão: <root>/results")
    m.add_argument("--semantic", action="store_true", help="Inclui o nível L4 (LLM)")
    _llm_args(m)

    d = commands.add_parser("demo", help="Aplica uma alteração do estudo (ex.: M11) e mostra o que cada nível aponta")
    d.add_argument("mutation", choices=[x.id for x in MUTATIONS])
    d.add_argument("--semantic", action="store_true", help="Inclui o nível L4 (LLM)")
    _llm_args(d)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except LLMError as exc:
        print(f"Erro de LLM: {exc}", file=sys.stderr)
        return 3


def _main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = find_root(args.root)
    except FileNotFoundError as exc:
        parser.error(str(exc))
    available = versions(root)
    for attr in ("version", "contract_version"):
        val = getattr(args, attr, None)
        if val is not None and val not in available:
            parser.error(f"Versão '{val}' inexistente; disponíveis: {', '.join(available)}")

    if args.command == "validate":
        bundle = B.load_bundle(root, args.version, args.contract_version)
        issues = B.check(bundle, root, B.LEVELS[args.level])
        _print({"valid": not issues, "level": args.level, "errors": [str(i) for i in issues]})
        return 2 if issues else 0

    if args.command == "fingerprint":
        bundle = B.synchronize(B.load_bundle(root, args.version))
        if args.write:
            base = B.api_dir(root)
            (base / "spec" / args.version / "specification.yaml").write_text(
                yaml.safe_dump(bundle["spec"], sort_keys=False, allow_unicode=True, width=110), "utf-8")
            (base / "contracts" / args.version / "openapi.yaml").write_text(
                yaml.safe_dump(bundle["contract"], sort_keys=False, allow_unicode=True, width=110), "utf-8")
            print(f"Marcas gravadas para {args.version}.", file=sys.stderr)
        _print({"contract_digests": bundle["spec"]["contract_digests"],
                "rule_fingerprints": {t["name"]: t["x-apidrift"]["rule_fingerprints"]
                                      for t in B.tags(bundle["contract"])}})
        return 0

    if args.command == "semantic-check":
        bundle = B.load_bundle(root, args.version, args.contract_version)
        verifier = ApiSemanticVerifier(_client(args))
        issues = verifier.check(bundle)
        _print({"valid": not issues, "model": verifier.llm.model,
                "errors": [str(i) for i in issues], "report": verifier.last_report})
        return 2 if issues else 0

    if args.command == "mutate":
        out = Path(args.output) if args.output else root / "results"
        verifier = ApiSemanticVerifier(_client(args)) if args.semantic else None
        res = run_api_mutation_study(root, verifier, out,
                                     prefix="api_mutation_llm" if verifier else "api_mutation")
        _print(res["levels"])
        return 0

    if args.command == "demo":
        mut = next(x for x in MUTATIONS if x.id == args.mutation)
        base = B.load_bundle(root, "v2")
        mb = apply(mut, base, B.load_bundle(root, "v2", "v1")["contract"])
        report = {"alteracao": mut.id, "artefato": mut.artifact, "descricao": mut.description,
                  "e_deriva": mut.drift, "niveis": {}}
        for level, cats in B.LEVELS.items():
            report["niveis"][level] = [str(i) for i in B.check(mb, root, cats)]
        if args.semantic:
            report["niveis"]["L4_semantica (só a IA)"] = [
                str(i) for i in ApiSemanticVerifier(_client(args)).check(mb)]
        _print(report)
        return 0
    return 1


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
