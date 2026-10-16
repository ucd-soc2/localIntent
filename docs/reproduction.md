# Reproduction

## Offline reproduction

From the repository root, run:

```sh
python reproduce.py verify
python reproduce.py analyze
python -m unittest discover -s tests -v
```

All three commands work without Ollama or model weights. Verification checks the repository checksum manifest, re-scores all saved outputs, reconstructs the paper repair prompts, and replays the grounded policy using recorded responses. Only the two dataset files and three compact result files are needed as evaluation data. The original archive and the larger source folder are not runtime dependencies.

The regression tests also replay every extended evaluation through the generation and repair entry points, checking each reconstructed prompt against its recorded hash before returning the saved response. Complete final validation results are compared by hash. A separate runner test stops and resumes a partial matrix and confirms that completed calls are not repeated. These checks use recorded responses and do not establish fresh model-generation or hardware-timing equivalence.

Select a subset for analysis or plotting:

```sh
python reproduce.py analyze --experiment paper
python reproduce.py analyze --experiment extended --cohort pooled
python reproduce.py plot --experiment extended --cohort supplemental
```

Plots require Matplotlib and NumPy. `requirements-plot.txt` records the supplied plotting dependency snapshot. Tables, figures and verification reports are generated under `build/` rather than bundled in the repository. Figure files can vary between platforms even when their plotted values are identical.

## Runtime and models

| Setting | Paper | Extended |
| --- | --- | --- |
| Ollama | 0.32.1 | 0.34.0 |
| Context window | 4,096 | 4,096 |
| Temperature | Unspecified, model/runtime default | 0 |
| Seed | Unspecified | 20261008 |
| top-p / top-k | Unspecified | Preserved native model defaults |
| Threads | Unspecified | 4 |
| Request budget | 120 seconds | 420 seconds |
| Streaming | No | Yes |
| Repair initial | Separate generation | Shared LocalIntent output |

The original experiment hardware was an Apple M4 MacBook Air with 16 GB unified memory. Precise historical environment fields are not fully captured for every run. The paper aggregation's hardware record reports Python 3.12.6 and a 0.32.1 client while the server was not reachable; the Monolithic run reports Python 3.14.3 and Ollama 0.32.1. These records do not establish a single Python version for every historical paper cell. The extended experiment's launcher path was recorded, but its exact Python version was not. New runs record their own environment.

The extended configuration pins all four model digests, templates and native parameters in `configs/models.json`. Downloading uses SHA256-addressed registry blobs and verifies size and hash; it does not resolve mutable tags to a newer model. Approximately 12.3 GB of model storage is required. If an upstream blob is unavailable, an exact matching local copy is required.

Historical paper model digests were not captured in the supplied paper manifests. A paper-profile rerun therefore checks the runtime version and model names, records actual model digests/templates/parameters, and pins them for continuation. It cannot certify that those weights equal the historical paper weights. The extended model snapshot must not be described as a verified historical paper snapshot.

## Extended runs

Install Ollama 0.34.0 separately. The executable can be on `PATH` or passed with `--ollama`.

```sh
python reproduce.py download-models
python reproduce.py verify-models
python reproduce.py serve --ollama /path/to/ollama
```

The server listens on `127.0.0.1:11439`, uses `.models/`, and limits loading to one model. In another terminal:

```sh
python reproduce.py check-api --experiment extended
python reproduce.py run --experiment extended --cohort supplemental
python reproduce.py run --experiment extended --cohort original
```

The two cohorts are separate runs. They are combined only for analysis. To combine fresh complete runs, concatenate their `records.jsonl` files and analyze the concatenated file; sample IDs are distinct between cohorts.

```sh
cat runs/extended-original/records.jsonl runs/extended-supplemental/records.jsonl > runs/pooled.jsonl
python reproduce.py analyze --records runs/pooled.jsonl --output build/fresh-pooled
python reproduce.py plot --records runs/pooled.jsonl --output build/fresh-pooled-figures
```

## Paper-profile runs

Use an Ollama 0.32.1 executable and a model directory containing the four named models. This can be a separately prepared directory; its exact contents are recorded by the runner.

```sh
python reproduce.py serve --ollama /path/to/ollama --model-dir /path/to/paper-models
```

In another terminal:

```sh
python reproduce.py check-api --experiment paper
python reproduce.py run --experiment paper --cohort original
```

Monolithic was historically a separate baseline run. The public runner executes all four methods using the paper generation settings and preserves the separate initial generation of the repair condition. New wall-clock times need not equal the historical scheduling and load conditions.

## Smoke runs and recovery

Inspect a plan without accessing the API:

```sh
python reproduce.py run --experiment extended --cohort original --dry-run
```

Run a small, explicitly separate sample:

```sh
python reproduce.py run --experiment extended --cohort original --models gemma2:2b --limit 2 --output runs/smoke
```

`--limit` selects the first N records; it is not a complete benchmark or a stratified subset. `--max-new N` stops at an evaluation boundary after at most N new evaluations. Repeat the identical command to resume. The runner validates completed checkpoints and reuses complete call caches. A changed prompt, source, dataset, configuration, endpoint or model identity is rejected. Use a new output directory for a changed experiment.

Transport retries are limited to three attempts. The runner stops after a persistent failure and can be manually restarted; it does not install a background supervisor or an operating-system startup task. Invalid model JSON and low metric scores are retained, not retried. New runs are not written into the published `results/` directories.

macOS/Linux file locking prevents concurrent writers to the same run. The default dedicated service limits model concurrency; do not run two independent matrices against it simultaneously. On macOS, `caffeinate -i python reproduce.py run ...` prevents idle sleep during long runs.
