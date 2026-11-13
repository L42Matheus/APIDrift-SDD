# APIDrift-SDD

IA generativa no *pipeline* de integração contínua para detectar a **deriva** entre a especificação, o contrato OpenAPI e o código de um serviço Spring.

O contrato OpenAPI é o que as equipes consumidoras, os *gateways* e os geradores de clientes usam; o código é o que executa. Quando um muda e o outro não, nada quebra: o serviço responde, os testes passam e o contrato continua prometendo o comportamento antigo. O APIDrift-SDD amarra requisitos, contrato e código numa especificação versionada e verifica esse vínculo a cada *pull request*, em níveis cumulativos:

| Nível | O que verifica | Interpretação |
|---|---|---|
| L1 | versões declaradas | versionamento convencional |
| L2 | + esquema do contrato x tipos Java, testes de conformidade | práticas usuais |
| L3 | + IDs, referências, *fingerprints* do código, *digests* do texto, cobertura | rastreabilidade SDD |
| L4 | + LLM compara o texto do contrato com o código Java | o contrato e o código dizem o mesmo? |

## Resultado do estudo exploratório

19 alterações (12 derivas e 7 mudanças benignas) sobre o serviço de exemplo:

| Nível | Derivas detectadas | Alarmes falsos | Decisões erradas liberadas |
|---|---|---|---|
| L1 | 2/12 | 0/7 | 9 |
| L2 | 6/12 | 0/7 | 1 |
| L3 | 10/12 | 2/7 | 1 |
| L4 (Claude Opus 5.5) | 12/12 | 2/7 | 0 |
| L4 (GPT-5.5) | 12/12 | 6/7 | 0 |

As duas derivas que só a IA detecta são as "ressincronizadas": o texto do contrato muda e as marcas são recalculadas, ou o limiar muda no código e o teste é ajustado para passar. Detalhes e limitações em [`paper/projeto_apidrift_sdd.pdf`](paper/projeto_apidrift_sdd.pdf).

## Estrutura

```
api/service/        serviço Spring Boot 3.3 (Java 21) com testes JUnit
api/spec/v1, v2/    especificação versionada (requisitos, regras, digests)
api/contracts/v1, v2/ contratos OpenAPI (tags com texto e extensão x-apidrift)
src/apidrift/       verificador (L1-L4), estudo de mutações e CLI
tests/              testes offline (sem rede e sem chave de API)
results/            resultados do estudo de mutações (results/gpt: GPT-5.5)
llm_cache/          respostas dos LLMs usadas no paper
paper/              projeto de pesquisa (LaTeX, modelo SBC) e figuras
.github/workflows/  testes e o portão de CI (api-gate.yml)
```

## Uso

Requer Python 3.10+ e JDK 21 (os testes de conformidade compilam o pacote de política com `javac`).

```bash
pip install -e ".[llm]"
python -m unittest discover -s tests       # testes offline
(cd api/service && mvn test)               # testes do serviço Spring

apidrift validate --level L3_sdd           # L1-L3 na versão 2
apidrift validate --contract-version v1    # contrato antigo com código novo: falha
apidrift mutate                            # estudo de mutações L0-L3

# L4 reproduzido a partir do cache, sem chave de API
apidrift mutate --semantic --offline --cache llm_cache/claude.json
apidrift mutate --semantic --offline --provider openai --cache llm_cache/gpt.json --output results/gpt
```

Para chamar os modelos de verdade, defina `ANTHROPIC_API_KEY` ou `OPENAI_API_KEY` no ambiente (nunca em arquivos) e rode `apidrift semantic-check`. Depois de revisar uma mudança, recalcule as marcas com `apidrift fingerprint --write`.

## Licença

MIT.
