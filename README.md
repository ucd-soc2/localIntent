# LocalIntent

**Outcome-specific structured generation for backend-compatible smart building automation with local LLMs.**

LocalIntent translates a natural-language request and a local state snapshot into an immediate command, a persistent automation rule, a clarification, or a rejection. It combines ordinary/rule routing, branch-specific generation, deterministic validation, and an optional repair policy.

This repository contains the implementation, prompts, datasets, saved model outputs, diagnostic scores, and analysis tools for the [paper](https://arxiv.org/abs/2610.23511).

[Reproduction guide](docs/reproduction.md) · [Method](docs/method.md) · [Evaluation](docs/evaluation.md) · [Results](results/README.md) · [Paper correspondence](docs/artifact_coverage.md)

## Start here

Python 3.10 or later is required; Python 3.12 is recommended for the recorded plotting dependencies. Offline scoring, verification and analysis use only the Python standard library. Model weights and Ollama are needed only to generate new model responses.

From this repository's root:

```sh
python reproduce.py verify
python reproduce.py analyze
python -m unittest discover -s tests -v
```

`verify` checks the published artifact hashes, recomputes all 2,480 saved evaluations, and checks 620 repair decisions using the recorded responses. Its report is saved to `build/verification.json`.

`analyze` produces metrics, paired repair statistics, mean/median/P95 latency, and stage-level timing under `build/results/`. These commands do not contact a model service or overwrite the published results.

The regression suite checks paper repair execution, reference isolation, checkpoint integrity, and interrupted-run continuation without generating new model responses.

To regenerate the figures:

```sh
python -m pip install -r requirements-plot.txt
python reproduce.py plot
```

The command generates PNG, PDF and SVG figures under `build/figures/`, together with their plotting tables. Generated figures, aggregate tables and verification reports are not stored in the repository. The plotting dependency snapshot was used with Python 3.12 on macOS arm64; other supported environments can install the plotting extra with `python -m pip install -e '.[plots]'`.

You can optionally install the CLI with `python -m pip install -e .`; `localintent` then provides the same commands as `python reproduce.py`. For an installation outside the checkout, pass `localintent --root /path/to/LocalIntent ...` so the CLI can find the datasets and result files.

## Experiments and datasets

| Experiment | Requests | Evaluations | Scored evaluations | Repair policy |
| --- | ---: | ---: | ---: | --- |
| Paper | Original 155 | 2,480 | 2,479 | Validation-guided repair |

The 155 requests comprise 54 commands, 54 rules, 31 clarifications and 16 rejections. All four methods are evaluated with `qwen2.5:3b`, `gemma2:2b`, `gemma3:4b`, and `gemma2:9b`.

The methods are **Monolithic**, **TwoStageGeneric**, **LocalIntent**, and **LocalIntent+SemanticRepair**. The repair condition uses validation-guided repair and generates its own initial outputs. Paired repair statistics compare the initial and final outputs of the repair condition.

The reproduction data consists of one input dataset and one compact result file. Inputs and references are stored once per request. Results retain model outputs, expected scores, repair evidence and measured timings for offline reproduction. See the [result format](results/README.md).

## Repository layout

```text
src/localintent/       Generation, normalization, validation and CLI
  prompts/            Prompts grouped by method and role
  repair/             Validation-guided repair policy
  evaluation/         Scoring, aggregation and offline verification
  experiments/        Serial execution and durable checkpoints
configs/              Paper experiment settings
data/                 Paper dataset
results/              Compact file of saved paper evaluations
docs/                 Method, evaluation, reproduction and limitations
provenance/           Source hashes and release checksums
tests/                Offline regression and recovery tests
reproduce.py          Repository command-line entry point
```

New model runs go under `runs/`; locally regenerated analyses and figures go under `build/`. Both directories are excluded from Git, as are downloaded models in `.models/`.

## Generate new model responses

The original hardware was an Apple M4 MacBook Air with 16 GB unified memory. The paper used **Ollama 0.32.1**. Run one model and one request at a time. The supplied runtime interface and file locking target macOS/Linux; Windows has not been validated.

Inspect the plan without connecting to Ollama:

```sh
python reproduce.py run --experiment paper --dry-run
```

Start Ollama 0.32.1 with a model directory containing the four named models:

```sh
python reproduce.py serve --ollama /path/to/ollama --model-dir /path/to/paper-models
```

The server listens on `127.0.0.1:11439`. Keep that terminal open. In another terminal:

```sh
python reproduce.py check-api --experiment paper
python reproduce.py run --experiment paper
```

Repeat the same command to resume an interrupted run. Completed responses and evaluations are checked before reuse; invalid model outputs are retained, while transport failures are retried a bounded number of times. A changed input, prompt, source file, model or configuration requires a new run directory. On macOS, prefix a long run with `caffeinate -i` to prevent idle sleep.

The [reproduction guide](docs/reproduction.md) covers the paper runtime, model-identity limits, smoke runs, output directories and analysis of new results. Fresh execution is supported, but new generation does not guarantee the historical scores or latency on a different system.

## Citation and license

Please cite the paper when using the implementation, datasets or results:

> Tianyang Liu, Jiayue Wang, Zhanhao Cheng, Changyang Wang, Shaoshu Zhu, Zhenghao Wu, and Hadi Tabatabaee Malazi. *LocalIntent: Outcome-Specific Structured Generation for Backend-Compatible Smart Building Automation with Local LLMs.* arXiv preprint arXiv:2610.23511, 2026. https://arxiv.org/abs/2610.23511

Recommended BibTeX citation:

```bibtex
@misc{liu2026localintent,
  title         = {{LocalIntent}: Outcome-Specific Structured Generation for Backend-Compatible Smart Building Automation with Local {LLMs}},
  author        = {Liu, Tianyang and Wang, Jiayue and Cheng, Zhanhao and Wang, Changyang and Zhu, Shaoshu and Wu, Zhenghao and Tabatabaee Malazi, Hadi},
  year          = {2026},
  eprint        = {2610.23511},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI},
  url           = {https://arxiv.org/abs/2610.23511}
}
```

The code and accompanying repository documentation are licensed under the [MIT License](LICENSE). Model weights are obtained separately and retain their respective upstream licenses.
