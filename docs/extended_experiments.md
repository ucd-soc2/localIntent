# Extended experiments

The extended study evaluates the original 155 requests and an additional 180 requests with the same four models and four method labels. Both cohorts use Ollama 0.34.0, temperature 0, seed 20261008, a 4096-token context window and four threads. Each model–request pair shares one LocalIntent initial between the base and grounded-repair conditions.

| Cohort | Valid repair pairs | APC improvements | APC regressions | Net APC change |
| --- | ---: | ---: | ---: | ---: |
| Original | 620 | 51 | 0 | +51 |
| Supplemental | 720 | 112 | 0 | +112 |
| Pooled | 1,340 | 163 | 0 | +163 |

The pooled gain is 12.16 percentage points within the paired repair condition. Of the 163 additional APC successes, 101 occur on rules and 62 on non-persistent requests. These non-persistent gains occur on commands, not clarification or rejection cases. Grounded repair triggers on 397 scenarios, accepts 353 candidates, and makes 50 additional model calls; deterministic edits account for many accepted repairs.

The original-cohort rerun is separate from the paper experiment. The runtime, sampling settings and repair policy changed, so differences in final scores are descriptive rather than a controlled estimate of the repair-policy change alone. The additional cohort was exposed during development and cannot serve as independent held-out confirmation.

Two original-cohort Gemma2:9b / TwoStageGeneric model outputs lack scores. The exported metrics retain their available-case denominators. The two extended cohort files contain the complete 5,360-evaluation matrix; the pooled analysis is computed from their union.

End-to-end repair time includes the LocalIntent initial execution. Report median and P95 as well as mean: extra repair calls can increase tail latency even when most requests require no call. Software and hardware differences prevent direct attribution of cross-experiment latency changes to the repair method.
