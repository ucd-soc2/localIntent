# Recorded results

This file contains the observations needed to reproduce the reported scores, repair comparisons and latency statistics without generating new model responses.

| File | Requests | Evaluations | Missing scores | Paired APC change |
| --- | ---: | ---: | ---: | ---: |
| [paper/records.jsonl.gz](paper/records.jsonl.gz) | 155 | 2,480 | 1 | +27 / 619 pairs |

## Compact record format

Each gzip file contains one JSON object per evaluation. `id` joins to the corresponding file under `data/`; instructions, states, references and outcome labels are not repeated in the results. The experiment and cohort follow from the file location. Generation settings are in `configs/paper.json`; historical model digests were not captured.

Common fields are `id`, `model`, `method`, `final`, `metrics`, and `elapsed_seconds`. `final` contains the normalized `output` and `checker_passed` flag. Expected metrics are retained so verification can compare newly computed scores against the recorded values. Missing scores remain `null`.

Paper records retain the final raw response and per-stage call durations. Repair records additionally retain the initial normalized output and structural diagnostics, candidate output, routing response, repair decision and repair-prompt hash. A rejected candidate's raw response is retained when it differs from the final response; an accepted candidate uses the stored final response. The source wrapper did not preserve a reliable raw initial response for accepted paper repairs. Those initial normalized outputs and diagnostics remain available for paired scoring and policy verification.

`elapsed_seconds` is the recorded end-to-end execution time. It is not replaced by the sum of model-call durations.

`localintent.artifacts.records()` joins the datasets and restores shared fields for analysis. It does not generate new outputs. For fresh runs, `runs/.../records.jsonl` remains a self-contained execution export accepted by `analyze --records` and `plot --records`.

## Generated outputs

```sh
python reproduce.py analyze
python reproduce.py plot
```

Analysis writes `metrics.csv`, `repair_pairs.csv`, `latency.csv`, `stage_latency.csv` and `summary.json` under `build/results/<experiment>/<cohort>/`. Plotting writes figures and plotting tables under `build/figures/<experiment>/<cohort>/`.

Each group includes method comparison, paired repair, P95/mean/median latency, overall metrics, stage latency, and repair trigger/acceptance figures. [Paper correspondence](../docs/artifact_coverage.md) maps these outputs to the manuscript.
