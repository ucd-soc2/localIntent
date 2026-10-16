# Method

The executable benchmark accepts an instruction, a timestamp and a device/sensor state snapshot. It produces an output for offline validation and scoring. The repository does not deploy the gateway, automation service or physical devices illustrated in the paper's architecture.

## Generation methods

**Monolithic** uses one prompt and one model call to select and generate an outcome. Its prompt receives compact generation context and the shared capabilities/schema representation.

**TwoStageGeneric** uses a four-way routing call followed by a prompt for Command, Rule, Clarification or Rejection. An invalid routing response falls back to clarification.

**LocalIntent** uses an ordinary/rule routing call. The ordinary prompt covers immediate commands, clarification and rejection; the rule prompt covers a persistent trigger–action rule. An invalid routing response invokes the temporal-cue fallback. The original prompt text, whitespace and input serialization are retained. LocalIntent uses indented instruction/state JSON; the generic baseline uses compact, outcome-specific capability context. These methods compare complete designs rather than isolated routing mechanisms.

`core.py` contains prompt assembly and routing. `schema.py` defines the capability registry, parsing, normalization, structural diagnostics, and diagnostic scoring primitives. Each prompt is available as a separate text file in `src/localintent/prompts/`.

## Validation

The validator parses JSON, checks raw parameter completeness, normalizes outputs, and checks registered identifiers, supported actions, required parameter fields, types, ranges, and rule constraints. The raw response, normalized candidate and structured diagnostics remain separate. A normalized output can exist even when validation fails; experimental scoring of that output does not make it eligible for actuation.

The six reference-based scores are calculated outside generation and repair. Dataset references are never supplied to a repair policy or included in a generated prompt.

## Repair policies

The **validation-guided** policy used by the paper combines structural diagnostics with explicit request/output semantic checks. It permits at most one additional model call. A candidate must pass the validator and the outcome/action-identity acceptance rules. A rejected candidate leaves the initial output selected for paired scoring. The paper repair condition generates its own initial response; it is not paired with the separately generated LocalIntent arm.

The **grounded** policy used by the extended experiments derives parameter changes from the request and state, protects unrelated fields, and checks command-family and action completeness. It can make deterministic edits and invokes a model at most once when necessary. All required actions must be supported by the input; the reference answer is not consulted. In these experiments the repair policy consumes the exact initial output from the LocalIntent arm.

`repair/parameters.py` implements grounded parameter operations and minimal-change acceptance. `repair/grounded.py` adds action-inventory and command-family checks. `repair/validation_guided.py` implements the paper policy. Diagnostic identifiers used inside frozen prompts remain part of the method's input contract.

## Execution

The runner uses a dedicated Ollama endpoint and serial model calls. Model-call caches include the prompt hash, input identity and generation settings. Complete responses are committed atomically. Transport failures are retried at most three times per call; poor scores and invalid model JSON do not cause retries. A rerun resumes valid checkpoints under the same manifest. Corrupt or incompatible checkpoints stop execution.

Fresh runs record their actual Python/platform information and model identity. Source and dataset hashes are bound to the run manifest. Previously recorded response time is retained when a cached response is reused after interruption; published historical timings are never replaced by fresh timings.
