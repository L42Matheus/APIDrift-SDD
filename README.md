# APIDrift-SDD

IA generativa no *pipeline* de integração contínua para detectar a **deriva** entre a especificação, o contrato OpenAPI e o código de um serviço Spring.

Protótipo de pesquisa que acompanha o projeto [`paper/projeto_apidrift_sdd.pdf`](paper/projeto_apidrift_sdd.pdf).

## O problema, em um exemplo

Uma API Spring de reembolsos publica um contrato OpenAPI. As equipes que consomem a API (o aplicativo, o atendimento) e a infraestrutura (*gateways*, clientes gerados) usam esse contrato. Ele diz:

> Cliente *premium* que cancela **até 1 hora** depois do despacho pode ser reembolsado.

O código diz o mesmo: `s.horasAposDespacho() <= 1.0`.

Meses depois, um desenvolvedor muda o código para `<= 2.0`. Um teste falha, ele ajusta o teste e o *pipeline* fica verde. O contrato continua dizendo "até 1 hora". Nenhum erro, nenhum alerta: a API passou a fazer uma coisa e o contrato promete outra. Isso é a **deriva**.

## O que o código deste repositório faz

Três coisas:

1. **Um serviço Spring de exemplo** (`api/service`). É uma API REST real (`POST /reembolsos/decisoes`) em Spring Boot 3.3 e Java 21, com cinco regras de negócio e testes JUnit. Existe em duas versões: na v1 não há a exceção *premium*; na v2, sim. Cada versão tem sua especificação (`api/spec`) e seu contrato OpenAPI (`api/contracts`).

2. **Um verificador** (`src/apidrift`, comando `apidrift`). Ele lê os três artefatos (especificação, contrato e código Java) e diz se ainda estão de acordo. A verificação é feita em níveis, do mais simples ao mais completo:

   | Nível | O que confere | Equivale a |
   |---|---|---|
   | L1 | se as versões declaradas batem | versionamento convencional |
   | L2 | + se os campos do contrato batem com as classes Java e se os testes de conformidade passam | o que as equipes já costumam fazer |
   | L3 | + se cada regra do código está ligada a um requisito e a uma seção do contrato, e se código ou texto mudaram sem revisão (por *hash*) | rastreabilidade orientada por especificação (SDD) |
   | L4 | + um LLM (Claude ou GPT) lê o texto do contrato e o código Java e diz se significam a mesma coisa | IA generativa como revisor |

   Qualquer divergência bloqueia a mudança. No repositório, isso roda como um portão no GitHub Actions (`.github/workflows/api-gate.yml`) a cada *pull request*.

3. **Um experimento** (`apidrift mutate`). Aplica 19 alterações ao serviço v2, 12 que criam deriva e 7 inofensivas (reformatar código, corrigir pontuação etc.), e mede o que cada nível detecta. Para as alterações no código, também conta quantas decisões erradas a API passaria a tomar se a mudança fosse liberada.

### Resultado

| Nível | Derivas detectadas | Alarmes falsos | Decisões erradas liberadas |
|---|---|---|---|
| L1 | 2/12 | 0/7 | 9 |
| L2 | 6/12 | 0/7 | 1 |
| L3 | 10/12 | 2/7 | 1 |
| L4 (Claude Opus 5.5) | 12/12 | 2/7 | 0 |
| L4 (GPT-5.5) | 12/12 | 6/7 | 0 |

As duas derivas que só a IA detecta são as do exemplo acima: a mudança vem acompanhada do ajuste do teste ou do recálculo das marcas, e todas as outras verificações ficam verdes. Os alarmes falsos e as limitações estão discutidos no paper.

## Como testar (passo a passo)

Requisitos: Python 3.10 ou mais novo e JDK 21. O Maven só é necessário para o passo 3.

**1. Baixar e instalar**

```bash
git clone https://github.com/L42Matheus/APIDrift-SDD
cd APIDrift-SDD
pip install -e ".[llm]"
```

**2. Rodar os testes do verificador** (não usam rede nem chave de API)

```bash
python -m unittest discover -s tests
```

**3. Rodar os testes do serviço Spring**

```bash
cd api/service && mvn test && cd ../..
```

**4. Ver o verificador funcionando**

```bash
apidrift validate                          # v2 sincronizada: "valid": true
apidrift validate --contract-version v1    # contrato antigo com código novo: lista as divergências
```

**5. Ver um caso que só a IA detecta**

```bash
apidrift demo M11 --semantic --offline --cache llm_cache/claude.json
```

Saída (resumida): L1, L2 e L3 não apontam nada, e o L4 responde:

```
[semantica] cancelamento/REG-PREMIUM-EXC: [limiar] O contrato, o REQ-05 e a própria
justificativa da anotação limitam a exceção premium a cancelamentos feitos até 1 hora
após o despacho (inclusive). O código usa horasAposDespacho() <= 2.0. ...
```

Troque `M11` por qualquer alteração de `M01` a `M12` (derivas) ou de `N01` a `N07` (inofensivas); a lista está em `src/apidrift/mutations.py` e na Tabela 4 do paper.

**6. Reproduzir os números do paper**

```bash
apidrift mutate --output /tmp/res                                                    # L0-L3
apidrift mutate --semantic --offline --cache llm_cache/claude.json --output /tmp/res  # L4 com Claude
apidrift mutate --semantic --offline --provider openai --cache llm_cache/gpt.json --output /tmp/res/gpt
```

Os arquivos gerados em `/tmp/res` são iguais aos de `results/`, de onde saem as tabelas e figuras (`python paper/gerar_figuras.py results paper/figs`, que requer `matplotlib`).

**Sobre `--offline --cache`:** as respostas que o Claude e o GPT deram no experimento estão gravadas em `llm_cache/`. Com essas opções, nenhuma chamada é feita e o resultado é exatamente o do paper. Para consultar os modelos de verdade, remova `--offline`, defina `ANTHROPIC_API_KEY` ou `OPENAI_API_KEY` no ambiente e use `--provider openai` para o GPT. As respostas podem variar um pouco entre execuções.

## Estrutura

```
api/service/          serviço Spring Boot (código, testes JUnit e casos de conformidade)
api/spec/v1, v2/      especificação versionada: requisitos, regras e digests do contrato
api/contracts/v1, v2/ contratos OpenAPI; a extensão x-apidrift liga cada seção às regras do código
src/apidrift/         verificador: java.py (lê as regras Java), bundle.py (L1-L3),
                      semantic.py (L4), mutations.py (experimento), cli.py (comando apidrift)
tests/                testes offline do verificador
results/              resultados do experimento (results/gpt: GPT-5.5)
llm_cache/            respostas dos LLMs usadas no paper
paper/                projeto de pesquisa (LaTeX, modelo SBC) e figuras
```

## Licença

MIT.
