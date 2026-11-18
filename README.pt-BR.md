# paretolab

*[Read in English](README.md)*

**Gerenciador de experimentos de otimização mono e multiobjetivo, agnóstico ao problema.**

Você traz o problema e os algoritmos, em qualquer linguagem, porque o paretolab os executa por um contrato de linha de comando. O paretolab cuida do resto da pipeline:

- **Tuning:** com o irace, por algoritmo e variante.
- **Execução:** em paralelo, com limite de tempo por execução.
- **Pausa e retomada:** a qualquer momento, inclusive no meio do tuning.
- **Indicadores:** hipervolume e IGD+ no multiobjetivo, distância ao ótimo no mono-objetivo. Calculados com o [moocore](https://github.com/multi-objective/moocore).
- **Estatística:** Friedman, Nemenyi e Wilcoxon-Holm, com diagramas de diferença crítica.
- **Relatórios:** tabelas, gráficos e uma interface web local.

> **Situação: pré-alfa (0.x).** A API, os formatos de arquivo e os nomes podem mudar sem aviso. Veja o [roadmap](docs/ROADMAP.md).

## Instalação

```bash
pip install git+https://github.com/tarcioee/paretolab
paretolab doctor
```

## Uso

```bash
paretolab validate project.yaml          # descreve o problema: docs/CONTRACT.md
paretolab validate experiment.yaml       # escolhe o que rodar
paretolab run experiment.yaml            # faz o tuning (se ativado), roda ou retoma e depois analisa: docs/EXECUTION.md
paretolab pause experiment.yaml          # ou Ctrl+C; rode `run` de novo para continuar
paretolab analyze experiment.yaml        # indicadores, testes, tabelas e figuras: docs/ANALYSIS.md
paretolab ui experiment.yaml             # tudo isso numa página web local: docs/WEB.md
```

A documentação detalhada em `docs/` está em inglês por enquanto. A versão em português sai junto com a v0.1.

Exemplos completos (TSP, ZDT1, DTLZ2) estão em [examples/](examples).

O tuning também precisa do R com o pacote `irace`; veja [docs/TUNING.md](docs/TUNING.md).

## Licença

[Mozilla Public License 2.0](LICENSE).

- **Usar o paretolab:** qualquer pessoa pode, para qualquer fim.
- **Modificar o paretolab:** as alterações nos arquivos do próprio paretolab precisam continuar abertas quando forem distribuídas.
- **Seu código:** seus algoritmos e plugins podem ter a licença que você quiser.
