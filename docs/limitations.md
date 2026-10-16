# Limitations

- Both cohorts were exposed during development or evaluation. The original prompt examples overlap some benchmark formulations, and the supplemental dataset was used during repair development. Results are not held-out generalisation estimates.
- The original rule dataset contains five duplicated instruction/state pairs with two retained reference actions. Keeping all 54 records gives those pairs double weight. Rule cases are clear executable rules and do not measure clarification or rejection of rule requests.
- The six diagnostics depend on the supplied reference and are not exhaustive measures of semantic validity. CH and LC have different meanings across request groups; clarification/rejection message quality is not measured.
- Deterministic validation does not establish complete reference agreement. Validator-rejected outputs can remain in the research records for scoring and are not certified for device execution.
- The paper and extended experiments differ in runtime, sampling and repair design. Comparisons between them are descriptive. Each model has one recorded generation run, and repeated evaluation across models does not create independent user requests.
- Zero observed paired regressions in the extended experiment does not guarantee harmless repairs on unseen inputs. The paper experiment contains three APC regressions.
- Runtime defaults, missing historical model digests, different hardware, and timing conditions limit exact regeneration. Offline score and policy checks are reproducible from saved records; model execution may produce different responses and latency.
- The repository evaluates outputs without physical actuation or concurrent building-state management. The supplied code is not a deployed building-control system.

Known differences between the camera-ready prose and source records are documented in [paper correspondence](artifact_coverage.md).
