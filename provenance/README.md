# Artifact provenance

`sources.json` identifies the supplied paper archive, datasets, original result exports, method modules and prompt files by SHA256. `checksums.json` covers the repository's source, configurations, datasets, compact result files and documentation.

The two dataset files preserve the instructions, states, timestamps, references and record order. Stable `original-NNN` and `supplemental-NNN` identifiers join them to the result records. Input object order is preserved because prompt serialization depends on it.

The compact result files preserve the observations needed for score, repair-policy and latency reproduction. Repeated inputs, references, full prompts, shared initial outputs, model metadata and verbose execution logs are omitted. Prompts are reconstructed from the source and checked against the saved hashes. Full extended validation results are likewise reconstructed and checked by hash. The [result format](../results/README.md) documents the stored fields and the paper's unavailable raw initial responses.

Aggregate tables, figures and verification reports are generated under `build/`. The source archives, third-party runtimes and model weights are not repository dependencies; model manifests and download hashes are in `configs/models.json`.
