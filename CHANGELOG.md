# Changelog

## 0.1.0 (2026-11-13)

Primeira versão, derivada do protótipo EvoPolicy-SDD e reposicionada para engenharia de APIs.

- Serviço Spring Boot 3.3 / Java 21 de decisões de reembolso, com regras anotadas com `@RegraPolitica` e testes JUnit (conformidade e MockMvc).
- Especificações e contratos OpenAPI v1 e v2; extensão `x-apidrift` com versão, requisitos e *fingerprints* das regras.
- Verificador em níveis L1-L3 (versão, esquema, conformidade, IDs, referências, *fingerprint*, *digest*, cobertura) e L4 semântico com Claude ou GPT.
- Estudo de mutações com 19 operadores e métrica de decisões erradas liberadas.
- Portão de CI (`.github/workflows/api-gate.yml`).
- Comando `apidrift demo <alteração>`: mostra o que cada nível aponta para uma alteração do estudo.
- Projeto de pesquisa em LaTeX (modelo SBC) para o Tema 7.
