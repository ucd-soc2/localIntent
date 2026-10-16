# Datasets

Each line contains `id`, `outcome`, `input`, and `reference`. `input` contains `userInstruction`, `current_state`, and `timestamp`. Input objects and reference answers retain the supplied values and order; dataset IDs are stable public identifiers.

| File | Command | Rule | Clarification | Rejection | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| [original.jsonl](original.jsonl) | 54 | 54 | 31 | 16 | 155 |
| [supplemental.jsonl](supplemental.jsonl) | 63 | 63 | 36 | 18 | 180 |
| Combined analysis | 117 | 117 | 67 | 34 | 335 |

`original.jsonl` contains the paper's 101 non-persistent and 54 rule records. Its inputs and references also underlie the extended original-cohort rerun. `supplemental.jsonl` contains the additional records used by the completed extended experiment. No second copy of the pooled dataset is stored; the loader concatenates the two files when requested.

The 54 original rule records contain 49 distinct instruction/state pairs. Five pairs have two retained admissible reference actions, so those inputs receive double weight. They are not deduplicated during scoring.

The paper's candidate records were manually checked for outcome type, state consistency, logical validity and JSON syntax. LLM-assisted checks were advisory and manually adjudicated. Some benchmark formulations overlap prompt examples; the supplemental records were also exposed during repair development. These datasets measure controlled development performance, not independently held-out generalisation.

The reference is used only by the offline scorer. Generation and repair receive the instruction, local state, timestamp and method-specific capabilities. See [evaluation](../docs/evaluation.md) for the diagnostic definitions and [provenance](../provenance/README.md) for source hashes.
