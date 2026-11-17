# CycloneDX evidence bound to a replacement plan

The optional BOM review connects **four independently supplied sources**: the native inventory, the native replacement proposal, the before CycloneDX JSON BOM, and the after BOM. A fifth file supplies exact byte hashes and explicit human slot mappings. It produces a native plan plus separate inventory/dependency/license evidence review. It does not manufacture constraints from BOM relationships.

## Reproducible synthetic example

```sh
python -m component_swap.bom_review plan examples/inventory.json examples/declared-match.json examples/before-bom.json examples/after-bom.json examples/bom-mapping.json --out bom-review
python -m component_swap.bom_review verify bom-review
python -m unittest discover -s tests -v
```

The native proposal preserves the declared embedding dimension and API while changing its version. Its existing native result is `declared_match`, unchanged by this extension. The two synthetic BOMs deliberately rename their local references, change a model's declared license expression, include a nested dataset, a consumer absent from the native inventory, and an unprojected service dependency. The review exposes those issues rather than turning the native match into an approval.

## Explicit mapping, not automatic identity

`bom-mapping.json` requires exactly:

```json
{
  "schema": 1,
  "sha256": {"inventory": "<exact file SHA256>", "replacements": "<exact file SHA256>", "before": "<exact file SHA256>", "after": "<exact file SHA256>"},
  "slots": [{"slot": "embedding", "before_ref": "old-embedding", "after_ref": "new-embedding"}]
}
```

There are 1..100 mapping rows. Slots must exist in the native inventory and appear once. Each non-null reference must name a projected component in the respective BOM and may be mapped only once on that side. `null` explicitly records missing evidence. Unmapped native slots and every unmapped projected BOM component remain visible. A name, PURL, hash or reference string does not automatically create a cross-BOM identity. The original core's stable slots are human-maintained identities; the mapping does not authenticate them. Names, BOM types/versions and native kinds/versions are displayed for human reconciliation, not silently made equal.

Any change to any of the four source files, even whitespace, requires deliberately renewing the mapping's hash binding. Mapping itself is also hashed in the report. Hashes detect inconsistencies, not ownership, accuracy or coordinated replacement of all files.

## Deliberately bounded projection

Only `bomFormat: CycloneDX` with `specVersion: "1.6"` or `"1.7"` is recognized. **This is not a full CycloneDX schema validator.** Standard-valid documents can exceed these limits or use unprojected features; accepting a document does not establish full schema validity.

The importer consumes top-level `components`, their nested `components`, and `metadata.component` with nested components, totaling at most 100 components. It records JSON Pointer locations and assembly parent/child relationships. A component requires bounded type/name strings; version is optional and remains unknown when absent. `bom-ref` is optional; when supplied it must be a nonempty, control-free string of at most 1,024 Unicode characters. Duplicate references among consumed components are rejected. Components without a ref remain visible by source pointer and cannot be matched by a fabricated reference. Other component identity fields, services, metadata, external references and root sections remain in original source bytes; unhandled field paths identify their coverage boundary. This is not validation of global reference uniqueness in all unprojected standard objects.

Consumed component `licenses` is retained as an uninterpreted parsed JSON array with its source pointer. It is not checked against full SPDX/CycloneDX license grammar. The exact original bytes remain in the source BOM. `modelCard` and `data` retain explicit presence, JSON Pointer and a hash of their canonical parsed value; their detailed semantics and licenses are **not** extracted. This is not proof that a model has an adequate model card, a complete training dataset inventory or known training-data permissions.

For every consumed object, unhandled sibling fields are listed by their root JSON Pointer; their entire subtree remains in the original file. A pointer is not a claim that every descendant was independently analyzed. Preserved whole license arrays and hashed modelCard/data subtrees have their own explicit handling mode instead of being silently discarded.

## Dependency semantics

At most 500 dependency records and 500 total `dependsOn` edges are accepted. Duplicate record refs and duplicate targets are rejected as ambiguous. Every record ref and target is a bounded string. `dependsOn: null` is rejected. A missing record gives `unknown_no_graph_record`; a record without dependsOn gives `unknown_dependsOn_absent`; an explicit empty array gives `declared_empty`. These are declarations, not discovered dependencies.

Only dependencies whose endpoints resolve to projected components become traversable edges. Unresolved targets and records with unprojected sources are reported; they may refer to services or externally described material. URLs and BOM-Links are never fetched. `provides` is listed as unhandled, never treated as a dependency. Nested assembly relationships are never converted into dependency edges.

Before/after edges are normalized only through explicit slot mappings. Unmapped or unresolved endpoints retain side-specific identities. If either graph state is unknown, a component is missing, or endpoints cannot be paired, `dependency_declarations_changed` is null and comparison status is `unknown_unmapped_or_unresolved`, **not true merely because side labels differ**. `known_mapped_edges_changed` separately compares the supported mapped subset when both graph declarations are available. `coverage_state_changed` reports whether the declaration states differ, without inventing a dependency conclusion.

Reverse impact traverses the entire projected graph independently on each side, including unmapped consumers. Seeds include mapped native changes, mapped BOM evidence changes, known mapped edge changes, and dependency comparisons needing review. Unknown correspondence is conservatively included with an explicit review reason. Paths absent from the traversed result are not proven unaffected: unprojected relationships or incomplete graphs can conceal more consumers. Arbitrary unmapped nodes are not silently paired across versions. Cycles terminate but no execution ordering is inferred.

## License and replacement boundaries

License expressions, IDs, names and acknowledgement fields remain as supplied, including AND, OR and WITH. No expression evaluation, compatibility decision, license recommendation or legal conclusion is made. Missing/empty license arrays mean missing/unspecified material, **not no obligations**. Parent licenses are not inherited. BOM document licenses, component/model licenses and dataset permissions are not interchangeable. Declared/concluded acknowledgement is the producer's assertion, not this tool's independent investigation.

The existing `core.plan` is executed on the original native files without injecting facts or requirements. A CycloneDX dependency does not imply a required version, typed equality, API behavior, data-model compatibility or successful replacement. Native `declared_match` stays a statement about human declarations only. No runtime tests, fabricated test results, evaluator calls, deployments or approval table are created.

## Bundle, replay and limits

The output directory contains exactly `inventory.json`, `replacements.json`, `before-bom.json`, `after-bom.json`, `mapping.json`, `native-plan.json`, `bom-review.json`, and `review.md`. All five source files preserve original bytes. Verification recomputes both the native plan and the projection/impact/license review and byte-compares every derived artifact; extra/missing/modified files fail.

Each input is at most 2 MiB and must be an ordinary non-symlink UTF-8 file. BOM JSON permits finite floating-point fields, including uninterpreted extensions; it rejects duplicate keys, nonfinite numbers/overflow, malformed Unicode and nesting at depth 24. Native inputs/mapping retain the original parser's stricter rules, including no floats and depth 16. BOM numeric lexemes are preserved in original bytes, not promised unchanged in parsed/canonical values. Output files are limited to 16 MiB and all generated bytes are preflighted before creating the destination. No existing output directory is overwritten. I/O failure may leave a partial new directory; verify before use. Parent directories/filesystems must be trusted.

Exit 0 means calculation or recomputation completed, not a safe replacement or legal approval. Exit 2 indicates an input/binding/projection/bundle/filesystem error. No network access, standard-schema downloads, browser UI, model calls, executable source content, implicit URL access or telemetry occur. Inspect full BOMs and inventories before sharing: they can disclose infrastructure, private names, metadata and copyrighted content. This is not anonymization.

## Official standard references

- [CycloneDX 1.6 JSON schema](https://cyclonedx.org/schema/bom-1.6.schema.json)
- [CycloneDX 1.7 JSON schema](https://cyclonedx.org/schema/bom-1.7.schema.json)
- [Dependency graph semantics and unknown coverage](https://cyclonedx.org/use-cases/software-dependencies/)
- [Assemblies do not imply dependencies](https://cyclonedx.org/use-cases/component-assemblies/)

The official schemas are Apache-2.0; no schema or third-party source code is embedded by this increment. Implementation and synthetic examples are original MIT-licensed work by walker512. No superiority, full standard compliance, measured user benefit or real migration is claimed.

## Validation performed

57 local synthetic tests passed on Linux/Python 3.12 with zero skips: the original 27 native regressions plus 30 added BOM tests. A separate review validated **only the two supplied positive synthetic BOM fixtures** against their official Draft-07 schemas, with jsonschema 4.26.0, referencing 0.37.0, FormatChecker enabled and network retrieval prohibited; both had zero errors. This fixture check is not a runtime dependency and does not make the projection a full schema validator.

The separately obtained schema SHA-256 values were:

- 1.6: `18f57f7482593bad9f21b4feed09084640cbeff419d62ad5090c5ceccca5b37d`
- 1.7: `73308edec3ab2d38bfffd993e96a042b594314143b6971a6e9ed98bbb6bd76ce`

Those schema downloads are not bundled. No full standard conformance suite, real provider BOM migration, browser acceptance, Windows/macOS or hosted CI was run for this increment.

### Markdown rendering boundary

All source-derived text emitted into `review.md` encodes explicit Markdown image/link/emphasis delimiters, backslashes and raw HTML delimiters. JSON and original BOMs retain the original text. Renderer-dependent bare URL or email autolinking may remain: inspect destinations before following links. This is not a general-purpose Markdown/URL sanitizer, and no browser or Markdown-renderer acceptance was performed.
