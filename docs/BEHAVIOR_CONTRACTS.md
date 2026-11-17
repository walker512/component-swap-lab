# Observed replacement contracts

This optional workflow closes one gap between inventory declarations and a real replacement: execute the same explicit, independently expected cases against baseline and candidate adapters. It is not an automatic migration system, benchmark, security sandbox, or production approval.

## Reproduce a real local replacement

Python 3.11+, standard library only. From a source checkout:

```sh
python -m component_swap.contracts run examples/contracts/inventory.json examples/contracts/replacement.json examples/contracts/contract.json examples/contracts/json_store.py examples/contracts/sqlite_store.py --out store-contract-review --trust-adapters
python -m component_swap.contracts verify store-contract-review
```

The baseline actually writes/reads a JSON file; the replacement actually writes/reads SQLite with committed transactions. They run in separate fresh temporary working directories. Three synthetic cases test missing keys, overwrite while preserving boolean/integer distinction, and Unicode values/key ordering. The contract binds to an actually changed inventory slot, and the resulting report includes conservative downstream impact. It does **not** migrate data from the JSON store into SQLite or prove durable recovery, concurrency, performance, schema migration, API equivalence, or rollback. Those need explicit separate tests.

A new run needs a new output directory. `verify` recomputes from saved evidence without executing adapters. To repeat the observations, issue a new `run` with the saved inventory, replacement, contract, baseline and candidate files and a new output. Hashes prove internal byte consistency, not authenticated execution or truth.

## Trust boundary

Only run adapter code you have reviewed and trust. `--trust-adapters` is mandatory. These Python scripts have your OS account privileges and can access files, processes and the network. Fresh cwd, filtered environment, `python -I`, no shell, timeout and bounded captured output are **not a sandbox**. The runner does not enforce offline execution. The included adapters use only synthetic local files; do not point an unreviewed adapter at production.

Use self-contained Python scripts reading one JSON request on stdin and writing exactly one JSON result on stdout. Python isolated mode ignores user-site/PYTHONPATH. Standard library and the interpreter's installed packages may be available, but dependency packaging/pinning is your responsibility. Do not spawn descendants/background processes: direct adapter termination does not guarantee termination of its descendants. Adapters must not rely on inherited secrets, current directories, import paths or shell configuration. Required dependencies must be explicitly configured outside the runner. The runner never installs adapters or their dependencies.

Each case is a fresh process. Use a sequence of operations inside a case if stateful behavior matters. Cases cannot communicate through their cwd, but trusted code can deliberately access other filesystem locations. Do not mistake this fixture convenience for containment.

## Contract format

Strict fields: `schema: 1`, `slot`, `timeout_ms`, `cases`. The slot must be actually changed by the supplied proposal. Limits: 1–20 uniquely named cases, 100–10,000 ms per direct adapter, 16 KiB canonical JSON per complete case, 128 KiB per adapter source. Every case has exactly `id`, `input`, `expected`. Expectations must be written independently of candidate results; matching two wrong implementations is not success.

Inputs/results allow finite JSON integers, strings, booleans, null, arrays and objects under the existing depth limit. Floating point is intentionally unsupported; use explicit integer units or strings. Duplicate keys and invalid UTF-8 are rejected. Typed canonical equality distinguishes true from 1 and preserves array order; object-key order is irrelevant. There are no tolerances, semantic similarity scores or model judges.

Stdout/stderr capture is limited to 16 KiB each. Exceeding either fails the execution. Stderr is retained only as a truncated length/hash; raw stdout is retained in base64. This is **not redaction**. The bundle also includes full adapter source, inventories and test inputs. Review all files before sharing; never include API keys or patient/customer data.

## Results and exit codes

- `passed`: expected typed JSON matched and process exited 0.
- `mismatch`: completed valid JSON result did not match the independent expectation.
- `invalid_output`, `process_error`, `timeout`, `output_limit`, `launch_error`, `open_streams`: execution/protocol not validated; not successful comparison.
- `comparison_complete` requires every baseline and candidate result to be passed or mismatch. Baseline execution failure is not called a candidate fix.
- A baseline mismatch → candidate pass is a resolved **supplied case**, not proof of a general fix. Baseline pass → candidate mismatch is a regression in that case. Both wrong remains failure even when outputs agree.

Exit 0: comparison complete and all candidate cases pass. Exit 1: comparison complete but at least one candidate mismatch. Exit 2: invalid input/output, failed evidence verification, or an incomplete comparison. Baseline mismatches remain explicit even if the candidate passes. None of these codes authorizes deployment. Planning and BOM commands retain their existing exit-code semantics.

## Evidence and limitations

Eight-file bundle: inventory.json, replacements.json, contract.json, baseline.py, candidate.py, observations.json, report.json and review.md. Source bytes and observations are bound by SHA-256; report is deterministically recomputed from records. Changed, missing, extra or symlinked files are rejected. Modifying all evidence consistently can forge another bundle; this is not a signed audit trail. Raw evidence is bounded but not automatically safe to publish.

The package complements mature conformance/evaluation tools with an inventory-bound local before/after contract and downstream handoff. No overall superiority, latency improvement, universal replacement coverage or real-user adoption is claimed. No provider API, paid model, external credential, production store or deployment is involved in the supplied regression suite. Browser GUI and Windows/macOS validation are not implied by Linux test results.
