# Agent-Native Repo Harness Map Migration Notes
**Date:** 14 April 2026

This note explains how the old SAN topology template maps into the new Agent-Native Repo Harness map.

## Why the format changed

The old file was a useful topology-first template, but the April 14, 2026 standard no longer treats code topology as the whole operating model. The new standard treats the repo as a kernel inside a larger harness. That means the mapping file must cover not only code nodes and edges, but also authority surfaces, runtime/session continuity, specialization, governance, automation, verification, and export boundaries.

The new primary file is:

- `agent-native-repo-harness-map-template-2026-04-14.json`

The companion validation schema is:

- `agent-native-repo-harness-map.schema.json`

## Field migration

| Legacy SAN v3.7 field | New location |
|---|---|
| `sanBlueprintEdition` | `manifestVersion` |
| `graphKind` | `codeGraph.generation.mode` |
| `authoritative` | `authority.precedenceModel.layers[*].authoritative` plus `repoKernel.systemOfRecordSurfaces[*].required` |
| `nodeBudgetPolicy` | `codeGraph.operationalLoadModel.policy` |
| `factors` | `codeGraph.operationalLoadModel.factors` |
| `agentOrientation.canonicalDoctrineSurface` | `authority.precedenceModel.layers` and `repoKernel.systemOfRecordSurfaces` |
| `agentOrientation.canonicalControlPlaneSurface` | `authority.precedenceModel` |
| `agentOrientation.canonicalDurableStateSurface` | `repoKernel.handoffArtifacts` and `runtimeFabric.sessionContinuity.durableStores` |
| `agentOrientation.defaultColdStartSequence` | `authority.precedenceModel.defaultColdStartSequence` |
| `agentOrientation.defaultExecutionEntrypoints` | `governancePlane.verificationSurfaces`, `runtimeFabric.executionEnvironments`, and `codeGraph.nodes[*].entrypoints.execution` |
| `agentOrientation.defaultVerificationEntrypoints` | `governancePlane.verificationSurfaces` and `codeGraph.nodes[*].entrypoints.verification` |
| `nodes[*].pathHints` | `codeGraph.nodes[*].paths` |
| `nodes[*].executionEntrypoints` | `codeGraph.nodes[*].entrypoints.execution` |
| `nodes[*].verificationEntrypoints` | `codeGraph.nodes[*].entrypoints.verification` |
| `nodes[*].declaredDependencies` | `codeGraph.nodes[*].dependencies.declared` |
| `nodes[*].observedDependencies` | `codeGraph.nodes[*].dependencies.observed` |
| `nodes[*].verificationScope` | `codeGraph.nodes[*].verificationRefs` |
| `nodes[*].dispersionReadiness` | `codeGraph.nodes[*].boundednessSignals` |
| `nodes[*].effectiveLoad` | `codeGraph.nodes[*].operationalLoad` |
| `nodes[*].status` | `codeGraph.nodes[*].status` |
| `edges` | `codeGraph.edges` |
| `integrity.declaredObservedDriftScore` | `integrity.dependencyDriftScore` |
| `integrity.lastTopologyReview` | `integrity.lastHumanReviewAt` or `codeGraph.generation.lastGeneratedAt` |
| `integrity.lastSanlockReview` | `maturity.criteria` evidence and `integrity.lastAgentReviewAt` |

## New first-class sections

The new format adds sections that did not exist in the old template:

- `authority`
- `repoKernel`
- `runtimeFabric`
- `specialization`
- `governancePlane`
- `maturity`

These are required because the current standard treats layered instruction precedence, durable session continuity, skills/subagents, hooks, worktrees, automations, and independent review as first-class operational surfaces rather than optional side notes.

## What stayed

The useful SAN insights were preserved:

- code nodes and edges remain first-class
- generated or hybrid topology is still encouraged
- operational load remains available as a local policy model
- cold-start orientation still matters
- dependency drift still matters
- boundedness of nodes still matters

## What changed in status

The old numeric node-budget logic is no longer constitutional law. It survives as an optional local policy model under `codeGraph.operationalLoadModel`.

The old single-surface control plane framing is replaced by an explicit layered precedence model.

The old topology-only frame is replaced by a full harness map.
