# Paper correspondence

The paper is available online at [arXiv:2610.23511](https://arxiv.org/abs/2610.23511). Its principal experiment uses the original 155 requests and four models. The paper result records were recovered from the supplied paper experiment archive; their main JSONL source hash matches the source identified by the later comparison material.

| Paper component | Public artifact |
| --- | --- |
| Method and routing, Sections 3–4 | `src/localintent/core.py`, `schema.py`, `methods.py`, `prompts/` |
| Validation-guided repair | `src/localintent/repair/validation_guided.py` |
| Dataset, Section 5.2 | `data/original.jsonl` and `data/README.md` |
| Metrics, Section 5.3 | `src/localintent/evaluation/metrics.py`, `docs/evaluation.md` |
| Method comparison, Figure 2 | `build/figures/paper/original/method_comparison.pdf` |
| Paired repair, Figure 3 | `build/figures/paper/original/repair_initial_final.pdf` |
| P95 latency, Figure 4 | `build/figures/paper/original/latency_p95.pdf` |
| Mean latency, Figure 5 | `build/figures/paper/original/latency_mean.pdf` |
| Median latency, Figure 6 | `build/figures/paper/original/latency_median.pdf` |
| Recorded call latency, Figure 7 | `build/figures/paper/original/stage_latency.pdf` |
| Individual outputs and scores | `results/paper/records.jsonl.gz` |
| Monolithic baseline | Included in the same paper result file, with `method=monolithic` |

Run `python reproduce.py plot --experiment paper` to create the figure files listed above. They are generated outputs, not bundled data. The paper matrix contains 1,860 main-method records and 620 separately generated Monolithic records. The compact export contains all 2,480 records once. The original 54 rule records preserve their 49 distinct inputs and five duplicated input pairs. The missing metric record is SemanticRepair / Gemma2:2b / `original-023`.

## Verified numerical correspondence

Paper non-persistent LocalIntent APC is 173/404 = 42.82%; repair final APC is 199/403 = 49.38%. Rule APC is 97/216 = 44.91% and 105/216 = 48.61%, respectively. The 619 scored repair pairs have APC 277 → 304, comprising 30 improvements and 3 regressions. The per-model net changes are Qwen +13, Gemma2:2b +2, Gemma3:4b +6 and Gemma2:9b +6. The other five paired metric totals are unchanged.

The recorded Gemma2:9b non-persistent mean latency is 22.26 seconds for LocalIntent and 29.60 seconds for SemanticRepair, matching the rounded values in Section 5.6. Result tables and figures are generated from the individual records.

## Validator-count discrepancy

Section 5.4 reports 511/620 LocalIntent outputs passing deterministic validation, with 277 passing outputs failing at least one reference-based metric. Counting `final.checker_passed` in the supplied individual records gives **510**, and **282** of these fail at least one metric. The supplied aggregate table also totals 510 schema/validator passes, and its cell exports agree with the combined export.

The source records are retained. The evidence does not establish whether the prose used a different validator calculation or contains a transcription error. The verifier reports both values and does not change the stored outputs to match the paper.

## Artifact scope

The source includes the experimental inference and evaluation implementation. The production gateway, physical device dispatcher and automation services in Figure 1 are not included in the supplied material. The architectural illustration remains available in the paper PDF.

The historical paper manifests do not pin model digests. Environment records contain different Python versions and include an aggregation-time client-only Ollama check. These are documented in the reproduction guide rather than converted into unsupported claims of exact hardware/software equivalence.

For accepted paper repairs, the original wrapper duplicated the selected final response in the `initial_raw_output` export field. The compact export omits that unreliable field. The initial normalized output, diagnostics, candidate, final output, and repair-prompt hash are sufficient for the documented offline checks, but not for reconstructing every original raw initial response byte.
