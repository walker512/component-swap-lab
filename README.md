# Component Swap Lab

**Review what a replacement would require, before changing a running system.**

A new offline inventory-and-replacement workbench by **walker512**. Give it explicitly declared components, dependency constraints and replacement candidates. It compares the old and proposed constraints, identifies mismatches and missing declarations, and lists reverse-dependency impact in a reproducible review bundle.

**It does not execute deployment, inspect real APIs, authenticate evidence or certify compatibility.** All inputs are user declarations. A `declared_match` must never be read as “safe to deploy.” Manual review is always required.

## Try three outcomes

Python 3.11+, no runtime dependencies. Run from this source directory:

```sh
python -m component_swap plan examples/inventory.json examples/mismatch.json --out review-mismatch
python -m component_swap plan examples/inventory.json examples/unknown.json --out review-unknown
python -m component_swap plan examples/inventory.json examples/declared-match.json --out review-match
python -m component_swap verify review-mismatch
python -m unittest discover -s tests -v
```

Read `review.md` or inspect `report.json`. Each bundle includes the complete inventory and replacement input files. Examples are entirely synthetic: changing an embedding dimension from 1536 to 768 violates the index's declared dimension requirement and potentially affects the answer service and UI. Omitting that declaration produces `unknown`, not a match. Keeping the same declared dimension produces only a declared match, not proof of real vector/model compatibility.

Existing output directories are never overwritten. An I/O error can leave a partial output directory; use a new destination and run verification before sharing. Generated files use UTF-8 bytes with LF, while source bytes are preserved verbatim. Optional installation: `python -m pip install .` provides `component-swap`; this source candidate is not a PyPI publication claim.

## Model an actual replacement

An inventory has `schema: 1` and `components`. Each component has:

- `id`: a stable slot such as `embedding`, not a provider credential or URL.
- `kind`: model, embedding, vector-store, orchestrator, client or other.
- `version`: a human-supplied label; no version-range semantics are inferred.
- `facts`: declared properties. Values are strings, booleans or integers with absolute value at most 10^12. A null/missing value is unknown. Use explicit integer units where needed; floats are rejected.
- `requires`: dependencies, each with `provider` and a nonempty `constraints` object. Requirements use exact **typed** equality: `true` is not integer `1`, and `"1536"` is not integer `1536`.

A proposal has `schema: 1` and `replacements`, using the same complete component format and existing stable IDs. A replacement is complete, not a partial patch: its dependency list replaces the old list. Unchanged facts and requirements must be included deliberately. Missing provider IDs, duplicate IDs, self-dependencies and unknown fields are rejected. No automatic discovery of undeclared requirements is attempted.

Bounds: 2 MiB per source input and 16 MiB per generated report file, 100 components, 30 facts and 30 dependency declarations per component, 500 edges and 500 individual constraints in the entire resulting graph. Strings/identifiers are bounded; inputs must be ordinary non-symlink files. Cyclic dependencies are allowed. Impact computation terminates on cycles, but does not infer an execution or rollback order.

## How to read results

- `baseline_status` distinguishes existing problems from those introduced by a proposal.
- `proposed_status` is mismatch, unknown, declared_match or no_constraints. No-constraint inventories do not receive an empty “all passed” result.
- Per-constraint before/after rows expose regressions, resolutions **in declarations**, changes to requirements, additions and removals. Removing an inconvenient requirement is visible; it is not evidence the problem disappeared.
- `affected_components` is the union of reverse-dependency reachability in old/new graphs starting from actually changed slots. It is conservative possible impact, not a runtime failure prediction. It includes the changed components themselves.
- The handoff checklist asks for real integration tests, state migration/restore checks, a canary and monitoring. It does not generate or run commands and cannot guarantee rollback, especially for stateful stores.

Exit 0 means planning or bundle consistency verification completed, even when the plan reports mismatch or unknown. Exit 2 means invalid input/output/bundle. There is deliberately no “production-safe” exit status. Read the report; do not turn successful execution into an automatic deployment gate.

## Trust and privacy

A bundle contains **complete supplied inventories**, including IDs, versions, facts and requirements. These may expose internal infrastructure or sensitive values. It is not anonymized, encrypted or automatically redacted. Never put API keys, passwords, customer prompts or private records into a public example. The supplied fixtures contain only fictional component names and capabilities.

`verify` recomputes from bundled inputs and compares deterministic report bytes. It does not check the live system or authenticated external evidence. A person who changes both inputs and generated outputs can create another internally consistent bundle. Hashes are not signatures, truth or freshness checks. There is no network access, model call, executable evaluator, source-code scanning or telemetry in this tool.

## Existing alternatives and bounded value

[CompatCanary](https://github.com/CognizenOrg/compatcanary) tests observed behavior of OpenAI-compatible APIs. [llmshift](https://github.com/DeChuks-hub/llmshift) documents model discovery, retirement tracking and migration evaluations. Their official project pages were reviewed; their complete workflows were **not executed or benchmarked here**. They provide capabilities this tool does not have, especially real endpoint/evaluation evidence. Do not claim they lack dependency planning solely because it was not tested.

This project packages a multi-component declared-constraint comparison, before/after diagnostics, conservative impact and a portable recomputation check. Equivalent checks can be implemented with ordinary graph/data tooling. No novel algorithm, overall superiority, measured time saving or real-user adoption is claimed. It complements, rather than replaces, runtime conformance tests. It is separate from cost benchmarking, configuration secret scanning and automatic deployment.

## Verification status

The unchanged native model has 27 public synthetic regression tests covering baseline/proposed changes, typed scalar distinctions, unknowns, removals, cycles, graph references, bounds, Markdown escaping, tampering, fixed output bytes and CLI plan/verify. Boundary fixtures cover 500 constraints per graph, disjoint before/after keys yielding 1,000 report rows, and sixfold Markdown escaping of `<`, `>` and backticks. Both report files are serialized and size-checked before the output directory is created; oversized reports are rejected rather than producing an unverifiable bundle. Verification uses the same separate report limit. Tests are local Linux Python 3.12; Windows/macOS have not been executed. FIFO and symlink cases can skip on unsupported platforms; skips are not passes.

This is a CLI with a text/Markdown review, not an interactive UI. No browser acceptance or real service migration is claimed. Independent audit is required before publication.

## License

MIT, copyright 2026 walker512. Original code and synthetic fixtures; no competitor code, real provider logs or private data are included.

## Optional CycloneDX replacement evidence (0.2.0)

The [BOM review workflow](docs/BOM_REVIEW.md) binds CycloneDX JSON 1.6/1.7 evidence and explicit human slot mappings to the original inventory and replacement proposal. It adds declared graph changes/unknown coverage, reverse impact including unmapped consumers, complete license-array preservation and model/data presence evidence. It never invents compatibility constraints from dependency edges or treats license expressions as legal conclusions. This is a bounded projection, not full standard validation or complete coverage of model/data licensing.

```sh
python -m component_swap.bom_review plan examples/inventory.json examples/declared-match.json examples/before-bom.json examples/after-bom.json examples/bom-mapping.json --out bom-review
python -m component_swap.bom_review verify bom-review
```

Increment validation: 30 new synthetic BOM regression tests plus the unchanged 27 native tests, **57 passed on Linux/Python 3.12, zero skips**. Coverage includes explicit identities and ref renaming, unknown graph coverage versus declared empty, assembly separation, raw license expressions, unmapped reverse impact, exact five-file binding, finite floats versus nonfinite rejection, field coverage, cycles, file limits, output preflight, real CLI and every bundled file's tamper detection. Windows/macOS, browser acceptance, deployed systems and competitor runtimes were not tested.
