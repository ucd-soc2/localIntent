# Evaluation

Each scored output has six binary diagnostics. Scores overlap and are not independent quality dimensions.

| Metric | Non-persistent requests | Persistent rules |
| --- | --- | --- |
| IU | Exact device–action agreement | Reference trigger sensor, action device and action |
| DI | Action-device set agreement | Action-device set agreement; excludes the trigger sensor |
| CH | Agreement on `needsClarification` | Agreement on rule/non-rule mode |
| APC | Actions and parameters match | Exact trigger object plus matching action and parameters |
| OFC | Normalized schema and capability compliance | Normalized rule schema and capability compliance |
| LC | Message-language agreement | Top-level rule structure |

APC tolerances are ±1 for temperature, brightness, level and channel, and ±5 for volume and openPercentage. Categorical values require exact agreement. Reference agreement is not an exhaustive semantic-validity judgment. In particular, clarification/rejection message quality is not measured, and DI excludes trigger sensors.

## Missing scores and denominators

The paper records contain one missing score for Gemma2:2b / SemanticRepair / `original-023`. The extended original cohort contains two missing scores for Gemma2:9b / TwoStageGeneric; the supplemental cohort has none. Missing scores are preserved as `null` and excluded from available-case metric denominators, exactly as in the supplied exports. Their locations are included in the generated `summary.json` files.

The verifier recomputes scores from the saved normalized output, using the corresponding reference and instruction. It checks both values and denominators. It does not substitute a new output for an invalid historical response. A missing-as-failure sensitivity analysis would require a separate explicitly labelled calculation.

## Paired repair

Only rows belonging to SemanticRepair are used for paired comparisons. Both initial and selected-final scores must exist. Summaries report improvements and regressions separately, alongside initial and final success counts, trigger counts, accepted candidates and additional model calls. A difference between the standalone LocalIntent arm and the repair arm in the paper is not a within-run repair effect.

## Latency

End-to-end latency uses individual recorded observations. Mean, median and P95 are recomputed for each model, method and request group. P95 uses linear interpolation between adjacent sorted observations. The pooled 335-request figures recompute from all observations; they do not average the two cohorts' means or percentiles without weighting.

Extended SemanticRepair end-to-end latency is the shared LocalIntent execution plus the additional repair execution. Deterministic checking and editing costs remain included even when repair makes no additional model call.

Stage-level plots use recorded model-call durations. Generic routing and generation and repair-initial durations are averaged over the whole applicable cohort. The repair-model stage is averaged only over scenarios with an actual additional model call, including rejected candidates. A missing call gives an undefined conditional mean, shown as “No call,” not a zero-second bar. Stage means have different denominators and should not be added as an end-to-end estimate.

## Outputs

`python reproduce.py analyze` writes the following files under `build/results/`: `metrics.csv` contains metric counts, rates, total counts and scored denominators; `repair_pairs.csv` contains paired metric changes; `latency.csv` contains end-to-end statistics; `stage_latency.csv` contains stage means and denominators; and `summary.json` records matrix completeness, missing scores and overall repair statistics.
