
# Agent-Native Repo Harness Standard
**Constitution-level standard for repo-centered autonomous software work**
**Date:** 14 April 2026

**One-sentence definition:**
An **Agent-Native Repo Harness** is a repo-centered software delivery system in which a fresh session can discover authority, recover durable truth, take bounded work on a reversible change surface, verify reality against independent runtime evidence, publish durable handoff state, and stop or escalate at policy boundaries without depending on hidden chat memory or live human cleanup.

> **Legacy names retired:** SAN Repo OS, SANOS, RaaOS, Repo OS.
> **Reason:** the repo is still central, but it is no longer accurately described as the whole operating system. The stronger April 2026 model is a **repo kernel inside a larger harness** that also includes durable session state, execution environments, and an evaluation / governance / automation plane.

---

## 1. Purpose

This document defines the highest current standard for repositories managed by coding agents.

It applies to both:
- greenfield repositories
- inherited repositories with existing code, history, debt, and production obligations

It is **not** a template repo, a folder layout, or a vendor playbook.

It is a **constitution** for what a serious repo-centered autonomous engineering system must be able to do.

If a fresh session cannot enter cold, discover authority, reconstruct state, take bounded work, change code safely, verify reality, publish durable progress, and leave the system healthier without relying on hidden chat memory or human cleanup, the system is not yet up to standard.

This document uses the normative words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** in their formal sense.

---

## 2. The model

### 2.1 The operating metaphor is revised

The old “repo as operating system” metaphor was directionally useful, but is now too narrow and too misleading to remain the canonical frame.

As of 14 April 2026, the strongest public systems no longer keep the whole agent system inside the repo. OpenAI persists thread history and reconnectable timelines in the Codex harness and App Server. Anthropic now explicitly separates **session**, **harness**, and **sandbox** as distinct interfaces, and describes Managed Agents as a **meta-harness** around long-horizon work. Durable workflow systems such as LangGraph and Temporal likewise treat recoverable execution state as first-class runtime infrastructure rather than as an incidental repo detail. [OAI-HARNESS-2026-02-11] [OAI-APPSERVER-2026-02-04] [ANTH-MANAGED-2026-04-14] [LANGGRAPH-OVERVIEW] [TEMPORAL-EVENTS]

**Canonical conclusion:** the repo is not the whole machine. It is the **kernel and durable local system of record** inside a larger harness.

### 2.2 Canonical architecture

An Agent-Native Repo Harness has three layers.

#### Layer 1 — Repo kernel
The repo kernel holds the durable, versioned local truth future sessions must be able to recover:
- code
- architecture surfaces
- operating doctrine
- verification entrypoints
- decisions
- current feature state
- risks
- durable handoff artifacts

#### Layer 2 — Runtime fabric
The runtime fabric carries the state and execution machinery that outlives one model turn and may outlive one client session:
- durable session or event history
- context compaction / trimming strategies
- resumable threads or checkpoints
- harness orchestration
- local / remote / cloud sandboxes
- worktrees or equivalent isolated checkouts
- external tools and resources

#### Layer 3 — Evaluation, governance, and automation plane
The governance plane keeps the system reliable under repeated autonomous use:
- independent review and evaluation
- policy hooks and approvals
- observability access
- recurring inspections
- repair loops
- background automations
- drift detection
- export controls

This three-layer model is the best current synthesis of OpenAI’s harness/App Server stack, Anthropic’s session-harness-sandbox split, MCP’s governed tool bus, and durable execution systems such as LangGraph and Temporal. [OAI-APPSERVER-2026-02-04] [ANTH-MANAGED-2026-04-14] [MCP-SPEC-2025-11-25] [TEMPORAL-EVENTS]

### 2.3 What “stateless” now means

A fresh stateless session remains the correct **test condition**.

It is no longer the correct full-system ontology.

The best 2026 systems wrap a mostly stateless model session inside increasingly stateful infrastructure: saved threads, checkpoints, event logs, worktrees, background agents, hooks, and durable runtimes. The standard therefore evaluates the **whole harness**, not merely the model session in isolation. [ANTH-HARNESS-2025-11-26] [OAI-APPSERVER-2026-02-04] [ANTH-MANAGED-2026-04-14]

---

## 3. Constitutional law

### 3.1 Cold-start bootability

A harness **MUST** let a fresh session enter cold and discover, without human retelling:
- where authority lives
- what state is current
- what work is available
- how to verify the environment
- how to publish durable progress before exit

A fresh session that must ask a human “what happened last?” is a failing system.

**Rationale:** both OpenAI and Anthropic explicitly frame effective agent work around what the agent can recover from repo-visible and harness-visible artifacts, not hidden memory. [OAI-HARNESS-2026-02-11] [ANTH-HARNESS-2025-11-26]

### 3.2 One authoritative precedence model

A harness **MUST** have one authoritative model for how instructions compose and override.

It **MUST NOT** depend on a single magical file.

Multiple instruction surfaces **MAY** exist, but:
- their precedence **MUST** be explicit
- conflicts **MUST** be avoided or mechanically resolved
- locality **SHOULD** matter
- nearer, more specific guidance **SHOULD** be able to refine broader guidance

If the underlying tool merges instructions without deterministic conflict handling, the repo authoring model **MUST** compensate by ensuring instruction surfaces do not conflict.

**Rationale:** OpenAI now documents a deterministic layered instruction chain for `AGENTS.md`; GitHub Copilot documents repository-wide, path-specific, and agent instructions, and warns that conflicting instructions can yield non-deterministic behavior. [OAI-AGENTS-2026] [GITHUB-INSTRUCTIONS-2026]

### 3.3 Repo-local durable system of record

The repo **MUST** remain the primary durable **local** system of record.

Essential operational truth **MUST NOT** exist only in:
- chat transcripts
- human memory
- Slack / email / ticket comments
- opaque runtime state
- ephemeral client sessions

The repo kernel **MUST** hold enough durable truth for a later session to recover:
- doctrine
- plans
- current feature state
- decisions
- risks
- verification entrypoints
- durable handoff artifacts

**Rationale:** OpenAI explicitly moved away from one giant instruction file toward a structured repo-local knowledge base used as the system of record; Anthropic’s long-running harnesses rely on progress artifacts plus version history to bridge stateless sessions. [OAI-HARNESS-2026-02-11] [ANTH-HARNESS-2025-11-26]

### 3.4 Durable handoff and session continuity

For any work that can cross turn or session boundaries, the harness **MUST** preserve restartable continuity through:
1. repo-visible handoff artifacts, and
2. a runtime/session mechanism appropriate to the task horizon

The durable session **MUST NOT** be confused with the active context window.

Compaction, trimming, and summaries **MAY** reduce active prompt size, but they **MUST NOT** become the only recoverable record of prior work.

For long-horizon tasks, the harness **SHOULD** maintain an append-only or equivalently recoverable event history outside the active prompt.

**Rationale:** OpenAI persists thread histories and reconnectable timelines; Anthropic’s Managed Agents explicitly separate session storage from the context window; Temporal and LangGraph both persist recoverable execution state to survive crashes and resumes. [OAI-APPSERVER-2026-02-04] [ANTH-MANAGED-2026-04-14] [LANGGRAPH-OVERVIEW] [TEMPORAL-EVENTS]

### 3.5 Bounded task and process contracts

A harness **MUST** give agents bounded work with explicit done conditions.

The standard unit of work is:
- narrow enough to understand
- coherent enough to verify
- small enough to review
- isolated enough to revert
- explicit enough to hand off

The harness **MUST NOT** normalize amorphous objectives such as “make the app better” without decomposition, checkpoints, or acceptance conditions.

**Rationale:** Anthropic’s long-running-agent work found one-feature-at-a-time progress critical; OpenAI’s harness work likewise emphasizes smaller building blocks and depth-first progress. [ANTH-HARNESS-2025-11-26] [ANTH-HARNESS-DESIGN-2026-03-24] [OAI-HARNESS-2026-02-11]

### 3.6 Versioned, diffable, reversible change control

Substantive mutation **MUST** occur on a versioned, diffable, attributable, reviewable, and reversible surface.

The implementation need not be Git, but the change surface **MUST** support:
- inspectable diffs
- checkpoints
- selective acceptance and rejection
- rollback or revert
- branch or equivalent isolation
- review before irreversible merge or release where policy demands it

**Rationale:** public agent systems now assume Git-native review and rollback surfaces; OpenAI’s review flows are diff-centric, and GitHub and Anthropic assume versioned reviewable work. [OAI-REVIEW-2026] [OAI-BEST-2026] [GIT-WORKTREE] [GITHUB-CLOUD-AGENT-2026]

### 3.7 Deterministic execution surfaces

A harness **MUST** expose stable, obvious ways to:
- bootstrap
- build
- test
- lint / typecheck / format where relevant
- start local runtime(s)
- run smoke checks
- tear down or clean up when needed

Repeated or coupled mutation **SHOULD** happen through rerunnable commands, codemods, generators, or equivalent deterministic mutation paths rather than manual multi-file synchronization.

**Rationale:** OpenAI’s best practices explicitly call for setup, build, test, lint, and verification guidance; Anthropic’s long-running harnesses start from verifying that the app works before further work proceeds. [OAI-BEST-2026] [ANTH-HARNESS-2025-11-26]

### 3.8 Independent verification and runtime truth

The harness **MUST** provide runtime truth independent of the generator’s self-report.

Depending on the system, proof **MUST** include some combination of:
- build results
- tests
- boot checks
- browser / UI checks
- logs
- metrics
- traces
- reviewable diffs
- explicit evaluator results

“Done” without reproducible evidence is not completion.

Observability **MUST** be treated as part of runtime truth, not as a side note.

**Rationale:** OpenAI exposes UI, logs, metrics, and traces directly to Codex in isolated local environments; Anthropic’s harness design relies on evaluator loops against running systems. [OAI-HARNESS-2026-02-11] [ANTH-HARNESS-DESIGN-2026-03-24]

### 3.9 Agent-legible architecture

The codebase **MUST** be legible to an agent under finite context.

It **MUST** have:
- explicit boundaries
- predictable directory semantics
- domain or feature names that mean something
- progressive disclosure
- limited need to load the entire repo at once

Knowledge that only exists outside the repo or outside accessible harness surfaces is operationally nonexistent.

**Rationale:** OpenAI explicitly states that “agent legibility is the goal” and that anything the agent cannot access in-context effectively does not exist; Anthropic’s context-engineering guidance emphasizes just-in-time, high-signal context rather than bulk loading. [OAI-HARNESS-2026-02-11] [ANTH-CONTEXT-2025-09-29]

### 3.10 Machine-readable topology and enforceable boundaries

When size or dependency complexity exceeds trivial scale, the harness **MUST** expose machine-readable topology or dependency surfaces.

Where tooling can generate the graph from code, generated topology **SHOULD** be preferred over hand-maintained topology files.

Architectural boundaries **SHOULD** be mechanically enforceable where possible.

**Rationale:** Nx automatically constructs project graphs, can extend them, can export them, and provides boundary enforcement to prevent chaos in larger workspaces. [NX-GRAPH] [NX-EXTEND-GRAPH] [NX-BOUNDARIES]

### 3.11 Specialization substrate

Once a single generalist session becomes noisy, context-saturated, or error-prone, the harness **MUST** support specialization.

The implementation may use:
- skills
- scoped subagents
- custom agents
- role-specific prompts with constrained tools
- agent teams

Specialized units **MUST** have explicit scope and **SHOULD** have appropriately restricted tool access.

**Rationale:** OpenAI, Anthropic, and GitHub all now expose first-party specialization surfaces for skills or custom agents; Claude Agent SDK and Codex both expose subagents; GitHub custom agents are versioned with the repository. [OAI-SKILLS-2026] [OAI-SUBAGENTS-2026] [ANTH-SKILLS-2026] [ANTH-AGENT-SDK-2026] [GITHUB-CUSTOM-AGENTS-2026]

### 3.12 Isolated parallelism

Parallel work **MUST** run in isolated contexts that share authority but do not trample one another’s working state.

The strongest current implementation is worktree-style isolation, but any equivalent that preserves separation, resumability, and safe handoff is acceptable.

Parallelism **MUST NOT** mean multiple agents scribbling into the same mutable checkout without isolation.

**Rationale:** OpenAI supports worktree-isolated threads and dedicated background worktrees for automations; Anthropic supports Git worktrees for parallel sessions and even subagent worktree isolation; Git itself provides the underlying model. [OAI-WORKTREES-2026] [ANTH-WORKFLOWS-2026] [GIT-WORKTREE]

### 3.13 Disciplined tool and I/O bus

External context and external actions **MUST** enter through explicit, governable adapters.

The harness **MUST** distinguish:
- internal repo truth
- external read context
- external write/action surfaces
- low-risk tools
- high-impact tools
- trusted tools
- untrusted tools

For large tool ecosystems, the harness **SHOULD** prefer progressive tool discovery, tool search, or code-execution mediation over flooding the model with every tool schema and every intermediate result up front.

**Rationale:** MCP is now the strongest open standard for connecting agents to external tools and systems; Anthropic explicitly argues that code execution with MCP can load tools on demand, filter results before they reach the model, and preserve privacy by keeping intermediate data in the execution environment. [MCP-SPEC-2025-11-25] [MCP-AUTH-2025-11-25] [ANTH-MCP-CODE-2025-11-04]

### 3.14 Trust envelope, approvals, and secret boundaries

“Hands-free” does **not** mean unbounded.

The harness **MUST** define:
- readable scope
- writable scope
- network policy
- destructive-action policy
- approval posture
- secret-handling rules
- tool trust model
- escalation boundaries

Generated code **MUST NOT** run in an environment where it can freely reach long-lived credentials unless that exposure is intentional, minimal, and governed.

Where possible, secrets **SHOULD** be kept outside the sandbox and mediated by proxies, short-lived tokens, or vault-backed interfaces.

Approval automation **MAY** use allowlists, rules, or classifiers, but the boundary **MUST** remain explicit and auditable.

**Rationale:** OpenAI defaults to workspace-limited sandboxes with network off and explicit approvals; Anthropic combines permission models with sandboxing and, in Auto mode, classifier-mediated permission skipping; Anthropic’s Managed Agents now explicitly separate the harness from secret-bearing infrastructure and route MCP auth via proxies and vaults. [OAI-SECURITY-2026] [ANTH-AUTO-2026-03-25] [ANTH-SANDBOX-2025-10-20] [ANTH-MANAGED-2026-04-14]

### 3.15 Independent evaluator / reviewer loop

For non-trivial autonomous work, the harness **MUST** provide an independent checking path distinct from the generator.

That checker may be:
- a human reviewer
- an automated reviewer
- an evaluator agent
- a hybrid review pipeline

But it **MUST NOT** be only the same agent asserting that it succeeded.

**Rationale:** Anthropic’s March 24, 2026 harness uses explicit generator/evaluator structure; OpenAI’s best-practices guidance says Codex should also test, check, and review, and notes that at OpenAI Codex reviews 100% of PRs; GitHub and Cursor now expose increasingly agentic code-review surfaces. [ANTH-HARNESS-DESIGN-2026-03-24] [OAI-BEST-2026] [OAI-GITHUB-2026] [CURSOR-BUGBOT-2026-04-08]

### 3.16 Continuous inspection, recovery, and drift control

The harness **MUST** become more reliable under repeated agent use, not less.

It therefore **MUST** include a standing mechanism that inspects for:
- doc/code drift
- stale instructions
- broken verification paths
- recurring failure patterns
- architecture erosion
- export leakage
- degraded review quality
- missing ownership or responsibility surfaces where policy requires them

It **SHOULD** be able to open or apply narrowly scoped corrective work when safe.

At higher maturity, this inspection **SHOULD** run continuously or on a schedule rather than only when a human remembers.

**Rationale:** OpenAI describes recurring cleanup tasks, quality grades, and targeted refactoring pull requests functioning like garbage collection; Codex and Cursor both now support background automations; hooks in both OpenAI and Anthropic ecosystems exist precisely because relying on model discretion alone is not enough. [OAI-HARNESS-2026-02-11] [OAI-AUTOMATIONS-2026] [OAI-HOOKS-2026] [ANTH-HOOKS-2026] [CURSOR-AGENTS-2026]

### 3.17 External and export-safe surfaces

If the harness produces outward-facing artifacts, it **MUST** separate:
- internal doctrine
- internal recovery state
- internal evaluation evidence
- outward-safe deliverables

Internal operator state **MUST NOT** leak by default into exported packages, published docs, client artifacts, or archives.

**Rationale:** the need for export-safe separation was already valid in the prior SAN criteria, and modern guardrail docs increasingly recommend protecting AI configuration and control files explicitly. Git provides mechanisms such as `export-ignore`; GitHub recommends protecting Copilot and MCP configuration files with `CODEOWNERS` and review rules. [GIT-ARCHIVE] [GITHUB-GUARDRAILS-2026]

---

## 4. Prohibitions

A serious harness **MUST NOT**:
- treat hidden chat memory as the system of record
- rely on one giant undifferentiated instruction manual as its only control surface
- let conflicting instruction files coexist without an explicit precedence model
- accept “done” without independent proof
- run generated code in the same place as unconstrained secrets by default
- allow parallel agents to share one mutable checkout without isolation
- expose every external tool and every intermediate result directly to the model when governed, on-demand access is possible
- preserve the old repo-OS metaphor as law when the actual architecture is clearly larger than the repo

---

## 5. Hard-fail conditions

A system is **not** an Agent-Native Repo Harness if any of the following are absent for the work it claims to support:

1. cold-start path to authority and current state
2. authoritative precedence model
3. repo-local durable system of record
4. resumability appropriate to the task horizon
5. versioned diffable reversible change control
6. deterministic execution and verification path
7. explicit trust envelope
8. independent verification or review path
9. continuous inspection mechanism for drift and decay

It also hard-fails if:
- it claims long-horizon autonomous work but has no durable session continuity
- it claims safe parallelism but has no isolated work contexts
- it claims hands-free operation but has no explicit approval or policy boundary
- it exports artifacts but has no export boundary

---

## 6. Human hands-free

**Human hands-free** means:

> a declared class of tasks can run from intake to bounded completion **without synchronous human intervention**, while remaining inside an explicit trust envelope, producing durable evidence of what changed and what was verified, and stopping or escalating when a policy boundary is reached.

This includes:
- implementation
- maintenance
- refactoring
- remediation
- upgrade work
- regression checking
- progress publication
- bounded rollback when policy allows

It does **not** include:
- unrestricted destructive access
- unrestricted network access
- secret exfiltration
- silent policy change
- proof by self-report
- hidden-memory dependency

This definition matches the direction of current approval, sandboxing, and classifier-mediated autonomy models without collapsing into “YOLO autonomy.” [OAI-SECURITY-2026] [ANTH-AUTO-2026-03-25] [ANTH-SANDBOX-2025-10-20] [MCP-SPEC-2025-11-25]

---

## 7. Strong 2026 default adapters and patterns

The following are not timeless constitutional law. They are the strongest **April 2026 defaults**.

### 7.1 Thin root map, deeper structured docs
A short root instruction map plus deeper structured docs is now the strongest control-plane pattern. OpenAI explicitly reports that the “one big `AGENTS.md`” pattern failed and replaced it with a map plus structured repo docs. [OAI-HARNESS-2026-02-11]

### 7.2 Layered instruction files with nearest-wins locality
OpenAI’s `AGENTS.md` chain and GitHub’s repo-wide + path-specific + agent-instruction model make layered locality the strongest current default, provided conflicts are disciplined away. [OAI-AGENTS-2026] [GITHUB-INSTRUCTIONS-2026]

### 7.3 Skills as the reusable workflow unit
Skills are replacing repeated long prompts as the main unit of reusable operational knowledge. OpenAI, Anthropic, and GitHub all now expose first-party skill or custom-agent surfaces, and both OpenAI and Anthropic align to the open Agent Skills standard. [OAI-SKILLS-2026] [ANTH-SKILLS-2026] [GITHUB-CUSTOM-AGENTS-2026]

### 7.4 Worktrees and equivalent isolated checkouts
Git worktrees are the strongest public default for isolated parallel work, background tasks, and review-safe experimentation. [GIT-WORKTREE] [OAI-WORKTREES-2026] [ANTH-WORKFLOWS-2026]

### 7.5 Persisted sessions, checkpoints, and durable runtimes
For long work, the strongest default is a persisted session/event history plus checkpointing or replay. OpenAI App Server, Anthropic sessions, LangGraph persistence, and Temporal event history all point in the same direction. [OAI-APPSERVER-2026-02-04] [ANTH-WORKFLOWS-2026] [LANGGRAPH-OVERVIEW] [TEMPORAL-EVENTS]

### 7.6 Hooks and rules for deterministic enforcement
Hooks now exist in both OpenAI and Anthropic ecosystems because prose alone is too weak for many high-value policies. The strongest default is to codify deterministic checks and side effects in hooks or equivalent enforcement points. [OAI-HOOKS-2026] [ANTH-HOOKS-2026]

### 7.7 MCP plus code-execution mediation
MCP is the strongest open adapter standard. For large tool surfaces, pairing MCP with code execution, tool search, or progressive disclosure is the strongest current pattern for context efficiency, privacy, and state handling. [MCP-SPEC-2025-11-25] [ANTH-MCP-CODE-2025-11-04]

### 7.8 Generated topology plus boundary enforcement
The strongest topology default is generated project graphs plus enforceable dependency constraints. Nx is the clearest public example. [NX-GRAPH] [NX-BOUNDARIES] [NX-EXTEND-GRAPH]

### 7.9 Background automations as the implementation of continuous inspection
At high maturity, recurring scheduled or event-driven agents are now the strongest implementation of continuous inspection and low-risk maintenance. OpenAI automations and Cursor’s agent surfaces make this explicit. [OAI-AUTOMATIONS-2026] [CURSOR-AGENTS-2026] [CURSOR-BUGBOT-2026-04-08]

### 7.10 Protected control files
Critical harness-control files — instruction surfaces, agent profiles, MCP config, and policy hooks — should be protected with code-owner review or equivalent safeguards. GitHub now recommends this directly for Copilot cloud agent environments. [GITHUB-GUARDRAILS-2026]

---

## 8. Application to inherited repositories

This standard is for **existing repos too**, not only clean-sheet projects.

For inherited repos, the correct move is usually **not** a total rewrite for aesthetic purity.

The correct move is monotonic hardening:
1. make authority explicit
2. make verification runnable
3. make changes diffable and reversible
4. make handoff durable
5. make trust boundaries explicit
6. expose topology
7. extract specialization surfaces
8. add continuous inspection

An inherited repo can meet this standard incrementally. What matters is whether each change increases recoverability, boundedness, legibility, and proof without destabilizing the system.

---

## 9. Frontier and open questions

The following are still active design questions, not settled constitutional law.

### 9.1 How much evaluator overhead remains necessary?
Independent checking is constitutional. The exact size and cost of evaluator loops may continue to fall as models improve. Anthropic’s latest harness work shows evaluator loops still matter today, but not necessarily in one fixed topology forever. [ANTH-HARNESS-DESIGN-2026-03-24]

### 9.2 How much session state should live outside the prompt?
Durable session logs are now clearly first-class, but the optimal line between active prompt context, compacted summaries, durable event history, and repo-visible memory remains unsettled. [ANTH-MANAGED-2026-04-14] [OAI-APPSERVER-2026-02-04]

### 9.3 How much of the harness should standardize across vendors?
MCP is the strongest open adapter protocol. But a full cross-vendor standard for session state, task durability, trust envelopes, and review semantics does not yet exist. MCP’s Tasks work and 2026 roadmap show movement in that direction. [MCP-CHANGELOG-2025-11-25] [MCP-ROADMAP-2026-03-05]

### 9.4 Repo harness or meta-harness?
At higher scale, a repo harness may itself be nested inside a larger **meta-harness** coordinating many brains, many hands, many sandboxes, and perhaps many repos. Anthropic’s Managed Agents is the clearest public signal that this layer is emerging. [ANTH-MANAGED-2026-04-14]

---

## 10. Maturity model

Score each constitutional invariant from **0** to **5**.

- **0** — absent
- **1** — present only through tribal or synchronous human intervention
- **2** — partially present but brittle
- **3** — reliable for routine supervised agent work
- **4** — reliable for bounded hands-free work inside a trust envelope
- **5** — self-auditing, drift-resistant, continuously improving

Interpretation:

- **Below standard**: any hard-fail invariant at 0 or 1
- **Harness-capable**: all hard-fail invariants at least 3
- **Hands-free capable**: declared task class completes reliably at 4 without synchronous intervention
- **Apex standard**: the repo sustains level 5 on inspection, review, recovery, and adaptation over time

The target of this document is not minimal compliance. It is the **apex** condition.

---

## 11. Final standard in one line

> An Agent-Native Repo Harness is a repo kernel inside a larger harness that can repeatedly cold-start, constrain, inform, verify, recover, review, and improve autonomous coding work without hidden memory, human cleanup, or uncontrolled authority.

---

## References

- **[OAI-HARNESS-2026-02-11]** OpenAI. *Harness engineering: leveraging Codex in an agent-first world*. 11 Feb 2026. https://openai.com/index/harness-engineering/
- **[OAI-APPSERVER-2026-02-04]** OpenAI. *Unlocking the Codex harness: how we built the App Server*. 4 Feb 2026. https://openai.com/index/unlocking-the-codex-harness/
- **[OAI-AGENTS-2026]** OpenAI Developers. *Custom instructions with AGENTS.md*. Accessed 14 Apr 2026. https://developers.openai.com/codex/guides/agents-md
- **[OAI-BEST-2026]** OpenAI Developers. *Best practices*. Accessed 14 Apr 2026. https://developers.openai.com/codex/learn/best-practices
- **[OAI-SKILLS-2026]** OpenAI Developers. *Agent Skills*. Accessed 14 Apr 2026. https://developers.openai.com/codex/skills
- **[OAI-SUBAGENTS-2026]** OpenAI Developers. *Subagents*. Accessed 14 Apr 2026. https://developers.openai.com/codex/subagents
- **[OAI-AUTOMATIONS-2026]** OpenAI Developers. *Automations*. Accessed 14 Apr 2026. https://developers.openai.com/codex/app/automations
- **[OAI-WORKTREES-2026]** OpenAI Developers. *Worktrees*. Accessed 14 Apr 2026. https://developers.openai.com/codex/app/worktrees
- **[OAI-REVIEW-2026]** OpenAI Developers. *Review*. Accessed 14 Apr 2026. https://developers.openai.com/codex/app/review
- **[OAI-SECURITY-2026]** OpenAI Developers. *Agent approvals & security*. Accessed 14 Apr 2026. https://developers.openai.com/codex/agent-approvals-security
- **[OAI-HOOKS-2026]** OpenAI Developers. *Hooks*. Accessed 14 Apr 2026. https://developers.openai.com/codex/hooks
- **[OAI-GITHUB-2026]** OpenAI Developers. *Use Codex in GitHub*. Accessed 14 Apr 2026. https://developers.openai.com/codex/integrations/github

- **[ANTH-HARNESS-2025-11-26]** Anthropic. *Effective harnesses for long-running agents*. 26 Nov 2025. https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- **[ANTH-HARNESS-DESIGN-2026-03-24]** Anthropic. *Harness design for long-running application development*. 24 Mar 2026. https://www.anthropic.com/engineering/harness-design-long-running-apps
- **[ANTH-MANAGED-2026-04-14]** Anthropic. *Scaling Managed Agents: Decoupling the brain from the hands*. 14 Apr 2026. https://www.anthropic.com/engineering/managed-agents
- **[ANTH-AUTO-2026-03-25]** Anthropic. *Claude Code auto mode: a safer way to skip permissions*. 25 Mar 2026. https://www.anthropic.com/engineering/claude-code-auto-mode
- **[ANTH-SANDBOX-2025-10-20]** Anthropic. *Beyond permission prompts: making Claude Code more secure and autonomous*. 20 Oct 2025. https://www.anthropic.com/engineering/claude-code-sandboxing
- **[ANTH-CONTEXT-2025-09-29]** Anthropic. *Effective context engineering for AI agents*. 29 Sep 2025. https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- **[ANTH-MCP-CODE-2025-11-04]** Anthropic. *Code execution with MCP: building more efficient AI agents*. 4 Nov 2025. https://www.anthropic.com/engineering/code-execution-with-mcp
- **[ANTH-HOOKS-2026]** Claude Code Docs. *Automate workflows with hooks*. Accessed 14 Apr 2026. https://code.claude.com/docs/en/hooks-guide
- **[ANTH-SKILLS-2026]** Claude Code Docs. *Extend Claude with skills*. Accessed 14 Apr 2026. https://code.claude.com/docs/en/skills
- **[ANTH-AGENT-SDK-2026]** Claude Code Docs. *Agent SDK overview*. Accessed 14 Apr 2026. https://code.claude.com/docs/en/agent-sdk/overview
- **[ANTH-WORKFLOWS-2026]** Claude Code Docs. *Common workflows*. Accessed 14 Apr 2026. https://code.claude.com/docs/en/common-workflows

- **[GITHUB-INSTRUCTIONS-2026]** GitHub Docs. *Adding custom instructions for GitHub Copilot CLI*. Accessed 14 Apr 2026. https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions
- **[GITHUB-GUARDRAILS-2026]** GitHub Docs. *Building guardrails for GitHub Copilot cloud agent*. Accessed 14 Apr 2026. https://docs.github.com/en/copilot/tutorials/cloud-agent/build-guardrails
- **[GITHUB-CUSTOM-AGENTS-2026]** GitHub Docs. *Custom agents configuration*. Accessed 14 Apr 2026. https://docs.github.com/en/copilot/reference/custom-agents-configuration

- **[MCP-SPEC-2025-11-25]** Model Context Protocol. *Specification (2025-11-25)*. 25 Nov 2025. https://modelcontextprotocol.io/specification/2025-11-25
- **[MCP-AUTH-2025-11-25]** Model Context Protocol. *Authorization*. 25 Nov 2025. https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- **[MCP-CHANGELOG-2025-11-25]** Model Context Protocol. *Key Changes*. 25 Nov 2025. https://modelcontextprotocol.io/specification/2025-11-25/changelog
- **[MCP-ROADMAP-2026-03-05]** Model Context Protocol. *Roadmap*. 5 Mar 2026. https://modelcontextprotocol.io/development/roadmap

- **[NX-GRAPH]** Nx Docs. *Explore graph*. Accessed 14 Apr 2026. https://nx.dev/docs/features/explore-graph
- **[NX-EXTEND-GRAPH]** Nx Docs. *Extending the Project Graph*. Accessed 14 Apr 2026. https://nx.dev/docs/extending-nx/project-graph-plugins
- **[NX-BOUNDARIES]** Nx Docs. *Enforce Module Boundaries*. Accessed 14 Apr 2026. https://nx.dev/docs/features/enforce-module-boundaries

- **[LANGGRAPH-OVERVIEW]** LangGraph Docs. *Overview*. Accessed 14 Apr 2026. https://docs.langchain.com/oss/python/langgraph/overview
- **[TEMPORAL-EVENTS]** Temporal Docs. *Events and Event History*. Accessed 14 Apr 2026. https://docs.temporal.io/workflow-execution/event
- **[GIT-WORKTREE]** Git Docs. *git-worktree*. Accessed 14 Apr 2026. https://git-scm.com/docs/git-worktree
- **[GIT-ARCHIVE]** Git Docs. *git-archive / export-ignore*. Accessed 14 Apr 2026. https://git-scm.com/docs/gitattributes
- **[CURSOR-AGENTS-2026]** Cursor. *New Cursor Interface*. 2 Apr 2026. https://cursor.com/changelog/3-0
- **[CURSOR-BUGBOT-2026-04-08]** Cursor. *Bugbot Learned Rules and MCP Support*. 8 Apr 2026. https://cursor.com/changelog
