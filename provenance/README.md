# Artifact provenance

`sources.json` identifies the supplied paper archive, datasets, original result exports, method modules and prompt files by SHA256. `checksums.json` covers the repository's source, configurations, datasets, compact result files and documentation.

The dataset file preserves the instructions, states, timestamps, references and record order. Stable `original-NNN` identifiers join it to the result records. Input object order is preserved because prompt serialization depends on it.

The compact result file preserves the observations needed for score, repair-policy and latency reproduction. Repeated inputs, references, full prompts, model metadata and verbose execution logs are omitted. Prompts are reconstructed from the source and checked against the saved hashes. The [result format](../results/README.md) documents the stored fields and the paper's unavailable raw initial responses.

Aggregate tables, figures and verification reports are generated under `build/`. The source archives, third-party runtimes and model weights are not repository dependencies. Historical paper model digests were not recorded.
