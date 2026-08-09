<!-- ownership: kit -->
# Context Pack Specification and Implementation Plan

Status: implemented in LBrain Kit 0.2.0

Decision baseline: approved product decisions from the Context Pack design review

Scope: normative Context Pack product and implementation contract

## Problem Statement

An LBrain is private by default, but selected context should be reusable outside the vault. Today a user can manually copy Markdown, but that loses selection rules, provenance, release history, update behavior, Skills, privacy review, and a stable way for another agent to understand the result.

The user needs a repeatable way to:

- continuously form durable work context from all enabled sources;
- organize that context in existing Projects, Areas, Knowledge, Identity Proposals, Outputs, or Inbox without adding a new category hierarchy;
- select an intentional subset of LBrain context;
- compile it into a portable, self-explanatory Markdown package;
- review exactly what will become public;
- publish each package as an independently versioned Git repository;
- keep the private LBrain in control of which Pack version it uses; and
- let recipients use the Pack directly with any capable agent, whether or not they use LBrain.

## Solution

Add Context Packs as a Kit-defined workflow with four separate objects:

1. **Context Intake** forms durable context inside the private LBrain from all enabled sources.
2. A **Pack Definition** records why a Pack exists and which LBrain material it selects.
3. A local **Candidate** compiles that selection into a normalized, portable Markdown tree for review.
4. An approved **Published Pack** lives in its own Git repository and is mounted inside the private LBrain as a Git Submodule.

LBrain remains the canonical source. A Pack is a compiled, versioned release artifact, not another editing authority. Changes should be made in LBrain or the Definition and then rebuilt.

The ordinary permission arrangement is:

- LBrain Kit: public;
- the user's LBrain: private;
- Published Packs: public;
- Pack Definitions and Submodule pointers: private because they live in the user's LBrain.

Private and trusted Packs remain supported, but public publication is the normal use case. Publication always requires an explicit user approval even when the Definition already declares public visibility.

## Domain Model

| Term | Meaning |
| --- | --- |
| LBrain | The user's private, canonical context repository. |
| Context Intake | A baseline or incremental scan across all enabled external sources that retains decision-complete durable context and provenance pointers. |
| Pack Definition | A user-owned Markdown note that declares Pack identity, audience, selectors, exclusions, Skills, and publication configuration. |
| Selector | A relative path or frontmatter query used to include LBrain material. |
| Candidate | A complete local build awaiting review; it has no publication authority. |
| Published Pack | An approved Git commit on the Pack repository's `main` branch. |
| Pack Release | A Published Pack commit identified by a CalVer tag. |
| Pack Repository | The independent Git repository containing only compiled Pack material and its explicit license. |
| Submodule Pointer | The private LBrain commit's exact reference to a Pack release commit. |
| Source Pointer | Safe provenance retained in a Pack without reproducing the LBrain's original directory structure or exposing private paths. |
| Fork | A new, independently identified Pack derived from an existing Pack while preserving applicable attribution and license obligations. |

## User Stories

1. As an LBrain owner, I want work context to be formed from all enabled sources, so that important decisions are not limited to whichever source I remembered to inspect.
2. As an LBrain owner, I want each intake run to scan every enabled source, so that a target Project receives complete context rather than a connector-specific fragment.
3. As an LBrain owner, I want durable Project context routed to the matching Project, so that AgentKey material accumulates under AgentKey without manual filing.
4. As an LBrain owner, I want non-target material routed to its own Project, Area, Knowledge, Identity Proposal, Output, or Inbox, so that a focused intake does not discard useful context.
5. As an LBrain owner, I want category and relationship metadata instead of deeper directory nesting, so that the filesystem stays simple.
6. As an LBrain owner, I want intake to retain durable conclusions and source pointers rather than mirror entire external systems, so that LBrain does not become a redundant archive.
7. As an LBrain owner, I want to configure intake sources and frequency through my agent, so that scheduling uses the automation system I already trust.
8. As an LBrain owner, I want scheduled intake to stop at safe local changes or Candidates, so that background work cannot publish private context.
9. As an LBrain owner, I want a stable `pack_id`, so that a Pack keeps its identity across rebuilds, releases, and repository moves.
10. As an LBrain owner, I want a Definition written as ordinary Markdown with small frontmatter, so that Obsidian and agents can both understand it.
11. As an LBrain owner, I want selectors to accept files, directories, and metadata queries, so that a Pack can span several Projects, Areas, Knowledge notes, and Skills.
12. As an LBrain owner, I want explicit exclusions applied after inclusions, so that a broad selector can still remove sensitive or irrelevant material.
13. As an LBrain owner, I want to preview selected files, rejected dependencies, and resulting changes, so that I know what a build will contain before it writes a Candidate.
14. As an LBrain owner, I want a Candidate to be built locally without publication, so that generation and disclosure remain separate decisions.
15. As an LBrain owner, I want a public Pack blocked when it reveals secrets, private paths, unsafe links, or unresolved private dependencies, so that mechanical mistakes do not become public disclosures.
16. As an LBrain owner, I want private dependencies resolved by sanitizing, omitting, or cancelling, so that the agent never silently broadens publication scope.
17. As an LBrain owner, I want to perform a semantic review after automated validation, so that technically valid but sensitive prose is still caught.
18. As an LBrain owner, I want first publication to create the public repository only after my approval, so that an unfinished Pack does not appear publicly.
19. As an LBrain owner, I want every Pack to have its own Git history and license, so that it can evolve and be shared independently of LBrain Kit.
20. As an LBrain owner, I want the Pack mounted as a Submodule in my private LBrain, so that one LBrain commit records the exact Pack version in use.
21. As an LBrain owner, I want `main` in a Pack repository to contain only the latest approved release, so that consumers can safely pull the default branch.
22. As an LBrain owner, I want every approved release tagged with CalVer, so that same-day releases remain ordered without a separate release database.
23. As an LBrain owner, I want Pack updates detected but never applied silently, so that my LBrain's Submodule pointer changes only with approval.
24. As an LBrain owner, I want Git and tags to provide release history and integrity, so that the Kit does not maintain duplicate hashes or a release ledger.
25. As an LBrain owner, I want to revoke a Pack on a best-effort basis, so that current users see a warning without pretending downloaded copies can be recalled.
26. As an LBrain owner, I want to fork a Pack under a new identity, so that derivatives have independent history while preserving attribution.
27. As a Pack recipient, I want `PACK.md` to explain the Pack before I load the rest, so that my agent can use progressive disclosure.
28. As a Pack recipient, I want normalized `context`, `knowledge`, `skills`, and optional `artifacts`, so that I do not need to understand the author's LBrain layout.
29. As a Pack recipient, I want relative links and portable Markdown, so that the Pack works outside the author's filesystem.
30. As a Pack recipient, I want to clone or download the Pack directly, so that adopting LBrain is not a prerequisite.
31. As a Pack recipient, I want included Skills to remain explicitly recognizable as Skills, so that behavior is not confused with descriptive context.
32. As a Pack recipient, I want `main` to update with the latest approved release and tags to preserve older versions, so that both simple and pinned consumption work.
33. As a Pack recipient, I want the Pack's visibility, status, version, provenance summary, and license stated clearly, so that I understand what I received.
34. As a Kit maintainer, I want Pack operations exposed through one Core Skill with deterministic internal tooling, so that agents have one stable entry point without a service layer.
35. As a Kit maintainer, I want the complete Core Skill set enabled by default with no Minimal profile, so that an initialized LBrain is functionally complete.
36. As a Kit maintainer, I want all Git tests to use temporary local repositories, so that verification cannot publish or depend on network access.
37. As a Kit maintainer, I want Kit upgrades to preserve Definitions, `.gitmodules`, and Submodule pointers, so that personal Pack configuration is never overwritten.
38. As a Kit maintainer, I want Pack repositories excluded from parent-vault indexing and validation, so that compiled material is not mistaken for canonical LBrain content.
39. As an LBrain owner, I want every scheduled Project to complete a historical baseline before incremental scans begin, so that older decisions are not silently omitted.
40. As an LBrain owner, I want a decision to retain its question, evidence, alternatives, rationale, tradeoffs, status, outcome, and source pointers when available, so that another agent can evaluate the reasoning instead of receiving only a conclusion.
41. As an LBrain owner, I want each intake run to prove source and anchor coverage, so that a connector search cannot be mistaken for a complete reading of the underlying material.

## Functional Specification

### 1. Context Intake

Context Intake is an agent workflow, not a hosted ingestion service or Kit daemon.

- On first configuration, the agent inventories currently available sources and asks whether the user wants scheduled intake, which sources to enable, and at what frequency.
- A scheduled Project keeps a compact `Intake Profile` in its existing Project note. The profile records context domains, enabled sources, stable anchors, source precedence, baseline status, and the last completeness review without storing credentials or raw connector cursors.
- A new Project starts in baseline mode. Baseline intake inventories and reads the relevant history behind every configured anchor; a recent-window scan, search result, or message listing cannot establish historical completeness.
- Incremental intake begins only after the baseline is complete. It uses the last successful external checkpoint with overlap and periodically revisits stable anchors to recover edits, late replies, and missed decisions.
- A run scans all enabled sources. A named target Project controls attention and reporting, not source coverage.
- Decision-bearing material is read at the page, topic, thread, change, or issue level before extraction. Discovery and full reading are reported separately.
- Each durable item is routed to an existing Project or Area when one matches. Synthesized domain knowledge goes to Knowledge. Proposed personal facts or preferences go through an Identity Proposal. Created artifacts go to Outputs. Uncertain material goes to Inbox.
- Classification such as work, life, or personal is metadata. It does not create a new `Space` entity or deeper fixed hierarchy.
- Intake stores the smallest durable representation: decision, rationale, action, outcome, status, or reusable learning, plus a source pointer. It does not preserve an external tool's complete thread, mailbox, page tree, or repository layout by default.
- The smallest complete decision representation retains, when present, its domain and status, date or span, question, material options or disagreements, evidence, conclusion, rationale and tradeoffs, consequences or actions, outcome or validation state, supersession or unresolved conflict, and all useful source pointers. Concision must not erase available reasoning.
- Later evidence updates the existing durable record and marks implementation, rejection, conflict, or supersession without deleting its prior state. A current-state Project note may link one adjacent `<Project>-Decisions.md` ledger when history would otherwise overwhelm the entry point; no new fixed directory hierarchy is introduced.
- Every run reports source and anchor status, inspected range or checkpoint, candidates found, records created or updated, duplicates and noise rejected, unresolved conflicts, changed files, and the next completeness review. Any failed, partial, stale when freshness is required, or unread required anchor makes the run partial.
- The agent follows each destination's existing permission contract. Scheduled intake cannot confirm Identity changes, publish Outputs, publish Packs, change remotes, or push Git history.
- Scheduling is delegated to the user's available agent automation facility. The Kit stores no scheduler, credentials, connector tokens, or background service.

### 2. Pack Definition

Definitions are user-owned notes stored under `Outputs/Context-Packs/`, outside the generated `Candidates/` and Submodule `Repos/` children.

The frontmatter contract contains:

| Field | Requirement | Meaning |
| --- | --- | --- |
| `type` | required | Fixed to `context-pack`. |
| `pack_id` | required | Stable, lowercase identifier used for repository and local identity. |
| `summary` | required | Human-readable purpose. |
| `status` | required | `draft`, `active`, or `archived`. |
| `visibility` | required | `private`, `trusted`, or `public`. |
| `audience` | conditional | Named audience required for `trusted`. |
| `repository` | conditional | Remote Git URL after a repository exists. |
| `submodule_path` | conditional | Registered local path after first publication. |
| `license` | conditional | Required before public publication. |
| `created` | required | Definition creation date. |
| `updated` | required | Last intentional Definition change. |

The Markdown body contains stable sections for purpose, includes, excludes, Skills, and build notes.

- An include or exclude entry is either a relative file or directory path, or an exact-match frontmatter query.
- Multiple fields inside one metadata query are AND conditions. Multiple selector entries are OR conditions.
- Exclusions are evaluated after all inclusions.
- Selectors cannot escape the LBrain root, follow an external symlink, or include a Pack repository.
- Duplicate selected content is emitted once.
- The Definition does not contain release rows or per-file hashes. Git supplies that history.

### 3. Selection and Dependency Resolution

Selection begins with every matching include selector, then applies exclusions, then follows only dependencies required to make selected material understandable.

- Dependencies include explicit Wikilinks, referenced Sources, embedded local assets, selected Skill resources, and each selected Skill's `lbrain.json` lifecycle sidecar.
- The preview distinguishes directly selected material from dependency material.
- A public Pack cannot retain a dependency whose visibility or contents would disclose private or trusted information.
- When a required dependency is unsafe, the operation pauses and offers exactly three outcomes: sanitize into portable public text, omit the dependent material, or cancel.
- The tool does not automatically change the visibility of the canonical LBrain note.
- Broken links, path escapes, ambiguous selectors, identifier collisions, and missing resources are hard failures.

### 4. Compiled Pack Contract

Every Candidate and Published Pack contains:

```text
PACK.md
SOURCES.md
context/
knowledge/
skills/
artifacts/
```

`PACK.md` and `SOURCES.md` are always present. The four directories are emitted only when non-empty.

- `PACK.md` is the manifest and first-read document. It states identity, summary, version, release status, visibility, audience when applicable, license, recommended loading order, capabilities, limitations, and an inventory of included sections.
- `SOURCES.md` records safe provenance and attribution. It must not reveal private local paths, private URLs, or omitted private dependencies.
- `context/` contains portable Project, Area, decision, outcome, and operating context.
- `knowledge/` contains topic knowledge that helps the recipient understand or act in the Pack's domain.
- `skills/` contains explicit, self-contained Skill packages selected by the Definition. Descriptive habits that do not meet the Skill contract remain context.
- `artifacts/` contains optional derived materials needed by the Pack.
- The compiler normalizes by semantic role and does not preserve the original LBrain directory tree.
- Internal links become portable relative Markdown links. Links that cannot be made portable block publication.
- A Pack must be usable by an agent without LBrain, Obsidian, a database, or a custom runtime.
- The system does not attempt to prevent a recipient from importing, copying, or feeding the files to an agent. License and disclosure boundaries communicate permitted use; they are not DRM.

### 5. Lifecycle Operations

The Context Pack Core Skill exposes the full lifecycle. There is no Minimal operation profile.

| Operation | Required behavior |
| --- | --- |
| `create` | Create a draft Definition with stable identity and no remote side effect. |
| `preview` | Resolve selectors and dependencies; report included, excluded, unsafe, changed, and unresolved material without writing a Candidate. |
| `build` | Produce or refresh a complete local Candidate after structural checks; never publish. |
| `publish` | Require successful validation and explicit approval; commit, tag, push, and update the private LBrain Submodule pointer. |
| `update` | Rebuild from canonical LBrain material, preview the diff, and publish a new release only after approval. It also detects newer remote Pack releases for consumers without moving pointers automatically. |
| `verify` | Validate Pack structure, manifest consistency, portability, license, and Git state when Git metadata is present. |
| `revoke` | Publish a prominent revoked state on a best-effort basis; never claim already downloaded copies were recalled. |
| `fork` | Create a new `pack_id` and independent history while preserving required attribution and license obligations. |

Definition lifecycle:

```text
draft -> active -> archived
  ^         |
  +---------+  when intentionally resumed
```

Release lifecycle:

```text
candidate -> published -> revoked
```

- Building never activates a Definition or publishes a release.
- First successful publication activates a draft Definition unless the user deliberately keeps the Definition in draft.
- Revocation does not automatically archive the Definition; a corrected later release remains possible.
- Archival is role-preserving and does not delete the independent Pack repository.

### 6. Git and Publication Model

Each long-lived Pack is an independent Git repository. Generated Candidates are written below the ignored `Outputs/Context-Packs/Candidates/<pack_id>` staging path. Published repositories are mounted below `Outputs/Context-Packs/Repos/<pack_id>` as Git Submodules of the private LBrain.

- The Pack repository's `main` branch always represents the latest approved release. Draft commits are not pushed to `main`.
- Every published release receives a CalVer tag in the form `YYYY.MM.DD.N`, where `N` starts at 1 for each date.
- The private LBrain records the exact release commit through its Submodule pointer. The pointer normally resolves to a tagged release.
- A Pack update may be detected automatically, but changing the Submodule pointer requires approval and a separate private LBrain commit.
- Git commit history and tags are the release ledger and integrity mechanism. The Kit does not add a release table or per-file hashes.
- A folder or ZIP copied without `.git` remains usable but cannot receive Git-level integrity verification or update discovery.
- Cloning a private LBrain with its public Packs uses standard recursive Submodule behavior. Cloning a Pack directly reveals nothing about the private parent repository.
- Pack repository visibility is independent of LBrain visibility. Public is the ordinary Pack target; private and trusted targets use appropriately restricted remotes.
- First publication creates the remote repository and adds the Submodule only after explicit approval. Before that moment, the Candidate remains in the local, rebuildable staging path.
- Built-in remote creation targets GitHub. An already existing standard Git remote may be used regardless of host. Automatic repository creation adapters for additional hosts are not part of the first implementation.
- Publishing, changing a remote, adding or removing a Submodule, pushing, tagging, revoking, and making a repository public are external or high-impact actions and require explicit authorization at the operation boundary.

### 7. Safety and Licensing

Automated validation hard-blocks:

- credentials, secrets, or secret-like configuration;
- absolute private filesystem paths;
- private or trusted URLs and identifiers in a public Pack;
- unresolved, ambiguous, or escaping paths and links;
- external or escaping symlinks;
- missing required manifest fields;
- missing or incompatible public licenses;
- private dependencies that have not been sanitized or omitted;
- missing Skill resources;
- mismatched `pack_id`, repository, Submodule path, version, release status, or Git tag;
- Candidate changes not represented in the publication preview; and
- publication from a dirty or unexpected Git state.

Automated validation cannot establish semantic safety. Before publication, the user receives the complete Candidate diff, disclosure summary, dependency resolutions, destination repository, visibility, license, and proposed version. Publication proceeds only after explicit approval of that review.

The Kit's MIT License covers Kit-owned Pack tooling and templates. It does not automatically license a user's Pack, selected context, Sources, artifacts, or Personal Skills. Every public Pack declares its own license, and every included third-party or Personal Skill must declare a compatible license in `lbrain.json`.

## Implementation Decisions

1. Context Pack is a Markdown-and-Git feature, not a service, database, custom registry, or web application.
2. LBrain remains canonical; Pack repositories contain compiled outputs only.
3. Existing Projects and Areas remain the filesystem organization. Work, life, personal, and cross-project relationships remain metadata; no `Space` abstraction is added.
4. Context Intake extends the existing capture and synthesis lifecycle instead of introducing connector-specific storage trees.
5. One new mandatory Core Skill provides the Context Pack lifecycle and delegates deterministic work to one internal command-line tool.
6. The existing Capture Skill gains the agent-facing intake and scheduling workflow; external connectors remain capabilities of the active agent environment.
7. All Core Skills, including Context Pack, are enabled by default. There is no Minimal profile.
8. The deterministic tool uses the Python standard library and installed Git executable. GitHub repository creation uses the already established GitHub CLI boundary rather than a new API client.
9. Pack Definitions use restricted frontmatter and exact Markdown sections so the validator can parse them without a general Markdown execution language.
10. Path selectors, exact-match metadata queries, exclusions, and explicit dependencies are sufficient for the first implementation. A general query language is not introduced.
11. Parent-vault traversal explicitly excludes both generated Candidates and Pack repositories. Pack verification runs separately against the selected Candidate or Pack root.
12. Every Candidate is built in the ignored, rebuildable staging path. For an existing Pack, preview compares that Candidate with the checked-out Submodule without changing the Submodule working tree before publication approval.
13. Git Submodules provide exact version composition. The parent repository owns `.gitmodules` and gitlinks as personal state; Kit upgrades must preserve them.
14. `main` plus CalVer tags is the complete branch and release model. Draft and release branches are not introduced.
15. Git supplies release history and content identity. A parallel release ledger and per-file digest manifest are intentionally omitted.
16. Public publication requires both mechanical validation and a human semantic review. Neither substitutes for the other.
17. Revocation is a forward notice, not deletion or recall.
18. Pack consumers do not need LBrain and are not restricted to an LBrain import path.
19. The first implementation supports GitHub repository creation and arbitrary pre-existing Git remotes; it does not build a provider adapter framework.
20. The current delivery phase may implement and test capability locally but may not modify the user's personal LBrain, initialize its private repository, create a real remote Pack repository, or publish content.

## Testing Decisions

### Highest test seam

The primary acceptance seam is the complete Context Pack lifecycle exercised through the deterministic tool against a synthetic LBrain and temporary local Git repositories. This verifies user-visible behavior across Definition parsing, selection, compilation, validation, Git commits, tags, Submodule pointers, updates, revocation, and forks without network or publication.

The Core Skill remains instruction-first and is checked with trigger and safety cases, matching the existing Skill test convention. Lower-level unit tests are added only where a failure cannot be made clear through the lifecycle seam.

### Required behavior coverage

1. A Definition can select several paths and metadata queries, apply exclusions, and deduplicate results.
2. Full-source intake routes synthetic durable items to the correct existing roles, sends ambiguity to Inbox, requires a historical baseline before incremental mode, preserves complete decision reasoning, and proves source and anchor coverage.
3. The compiler emits `PACK.md` and `SOURCES.md`, emits only non-empty semantic directories, and does not preserve the original tree.
4. A recipient fixture can understand the Pack from `PACK.md` and resolve every included relative link without access to the source LBrain.
5. Public build validation blocks private dependencies, secrets, private paths, unsafe links, escaping selectors, symlinks, missing licenses, and missing Skill resources.
6. Sanitizing or omitting a blocked dependency produces a reviewable Candidate; cancelling leaves publication state unchanged.
7. Preview is read-only, build has local effects only, and neither creates a remote, tag, or Submodule pointer.
8. First publication is simulated with a temporary bare remote and produces `main`, the correct CalVer tag, and a parent Submodule pointer to the same commit.
9. A second same-day release increments `N`; a release on another day starts again at 1.
10. Pack `main` never contains an unapproved Candidate commit.
11. Update detection reports a newer release without changing the parent pointer; approved update changes it explicitly.
12. Git verification detects a dirty tree, wrong tag, mismatched manifest version, and unexpected pointer.
13. A copied Pack without `.git` passes structural verification while clearly reporting that Git integrity and update checks are unavailable.
14. Revocation updates the current public state in the simulated remote without claiming historical copies were removed.
15. Fork creates a new identity and history while preserving required attribution and license material.
16. Parent LBrain validation skips initialized Pack Submodules and separately verifies Definitions and registrations.
17. A formal Kit upgrade preserves user-owned Definitions, `.gitmodules`, Submodule pointers, and existing Pack repositories.
18. All Git publication tests use temporary local repositories and cannot access a network remote.
19. Intake cases reject a recent-window or search-only scan as a complete baseline and reject a conclusion-only record when the available source contains material reasoning.

### Existing prior art

- The current workflow smoke tests already create temporary Kit, personal, and bare Git repositories and verify release upgrades.
- The current tooling smoke tests already copy an isolated LBrain and exercise read-only validation and runtime installation.
- Existing Core Skills use `tests/cases.md` for triggers, negative cases, expected behavior, and safety edges.

## Acceptance Criteria

Implementation is complete only when all of the following are true:

1. The full Context Pack lifecycle is available through the mandatory Core Skill.
2. Definitions, Candidates, Published Packs, releases, and Submodule pointers obey the state and ownership contracts above.
3. A synthetic work-context Pack can be built and consumed without the source LBrain.
4. All hard safety failures are demonstrated by runnable tests.
5. Preview and build produce no remote side effects.
6. Publication tests prove commit, tag, remote, and Submodule behavior entirely with local temporary repositories.
7. Existing LBrain capture, weave, retrieve, review, write, Skill management, and Kit upgrade behavior remains intact.
8. The repository validator passes and the full test suite passes.
9. Setup, upgrade, ownership, visibility, Outputs, Skills, and migration documentation agree with the implemented behavior.
10. No real Pack repository is created and the user's personal LBrain remains unchanged during this implementation phase.

## Implementation Plan

The plan is ordered by dependency. Each task should be an independently reviewable local commit once implementation is authorized. No task in this plan is authorized by this specification-only change.

### Task 1 — Establish contracts and fixtures

**Changes**

- Add the `Outputs/Context-Packs/` semantic contract and Definition template.
- Extend ownership, permission, visibility, Git, setup, and upgrade contracts for Definitions, Candidates, Pack repositories, `.gitmodules`, and gitlinks.
- Add a small synthetic Definition and source fixture under Kit examples.

**Verification**

- The validator accepts the untouched Kit and the new synthetic Definition.
- Ownership is unambiguous for every new path and Git artifact.
- No user-owned or Seeded file becomes Kit-overwritable.

**Depends on:** specification approval.

### Task 2 — Extend validation boundaries

**Changes**

- Teach parent LBrain validation to exclude generated Candidate and Pack repository contents from recursive note, link, visibility, resource, and symlink scans.
- Validate Definition metadata, selectors, repository registration, audience, license, and lifecycle consistency.
- Add standalone Pack-root structural validation for compiled output.

**Verification**

- Parent validation neither double-indexes nor treats a Submodule Pack as canonical LBrain content.
- Invalid Definitions and invalid compiled Packs fail with actionable messages.
- Existing validator behavior remains unchanged outside Context Packs.

**Depends on:** Task 1.

### Task 3 — Build one deterministic Pack tool

**Changes**

- Add one standard-library command-line entry point for `preview`, `build`, and `verify`.
- Implement restricted Definition parsing, selector evaluation, exclusion, dependency discovery, normalization, portable link rewriting, manifest generation, and safe provenance generation.
- Produce deterministic output ordering so identical LBrain inputs create an empty Git diff.

**Verification**

- Lifecycle tests cover multi-scope selection, metadata queries, exclusions, dependency handling, normalized output, portability, and idempotent rebuilds.
- Preview leaves the filesystem unchanged.
- Build writes only the ignored, rebuildable Candidate staging root.

**Depends on:** Tasks 1 and 2.

### Task 4 — Add the Core Skill and Context Intake behavior

**Changes**

- Add the mandatory Context Pack Core Skill with all eight lifecycle operations and safety cases.
- Enable it for every supported runtime and update runtime-installation expectations.
- Extend Capture guidance for manual and scheduled all-source Context Intake, semantic routing, durable-only retention, and automation boundaries.

**Verification**

- Positive, negative, and safety trigger cases cover the Core Skill.
- A synthetic intake demonstrates complete source coverage, target-focused reporting, non-target routing, and Inbox fallback.
- The installer adds the new Core Skill without regressing idempotence or Personal Skill handling.

**Depends on:** Tasks 1 and 3.

### Task 5 — Implement local Git and Submodule lifecycle

**Changes**

- Extend the deterministic tool with local repository initialization, release commits, CalVer tags, Submodule registration, pointer updates, update detection, revocation, and fork behavior.
- Require clean and expected Git state before any release transition.
- Keep every network-capable or remote-changing action behind preview and explicit approval gates.

**Verification**

- Temporary local repositories prove first publication, repeat publication, update detection, pointer approval, revocation, and fork behavior.
- Failed operations leave both parent and Pack repositories recoverable and report the next safe action.
- No test command can reach a network remote.

**Depends on:** Tasks 2 and 3.

### Task 6 — Add GitHub publication boundary

**Changes**

- Add first-publication orchestration that can create a GitHub repository after explicit approval or attach an existing standard Git remote.
- Present destination owner, repository name, visibility, license, proposed tag, Candidate diff, and disclosure summary immediately before publication.
- Keep GitHub-specific behavior at the external command boundary without a provider abstraction layer.

**Verification**

- Command construction and approval requirements are tested without invoking GitHub or a network.
- Missing authentication, repository collisions, rejected approval, and partial failure produce safe recovery instructions.
- Existing-remotes flow remains provider-neutral.

**Depends on:** Task 5.

### Task 7 — Complete end-to-end and upgrade coverage

**Changes**

- Add an end-to-end synthetic work Pack tracer.
- Extend the formal Kit upgrade fixture to include a user-owned Definition and local Pack Submodule.
- Add copied-folder verification coverage for recipients without Git metadata.

**Verification**

- The tracer proves private LBrain selection through portable Pack consumption.
- The upgrade test preserves all personal Pack state.
- The complete test suite and Kit validator pass together.

**Depends on:** Tasks 4, 5, and 6.

### Task 8 — Document and release the Kit capability

**Changes**

- Update Kit navigation, Setup, Outputs, Skills, security guidance, changelog, version, and migration instructions.
- Document owner workflows, recipient workflows, Git Submodule restoration, public disclosure review, updates, revocation limitations, and Git-without-`.git` limitations.
- Record that the first real Pack publication belongs to the later personal LBrain migration phase.

**Verification**

- Every documented command maps to a tested behavior.
- A cold-start reader can distinguish Kit upgrade, private LBrain history, and independent Pack history.
- Release validation passes before any local release commit; pushing or publishing remains separately authorized.

**Depends on:** Tasks 1 through 7.

## Out of Scope

- Modifying or migrating the user's current personal LBrain.
- Initializing or pushing the user's private LBrain repository.
- Creating a real GitHub Pack repository or publishing real context during this implementation phase.
- Automatically applying Kit or Pack updates.
- A hosted service, database, Pack registry, web UI, or custom scheduler.
- Built-in Gmail, Notion, Zulip, or repository connectors; Context Intake uses connectors already available to the active agent.
- A new `Space` entity or deeper work/life/personal directory hierarchy.
- Mirroring complete external source structures or retaining all raw messages.
- Git Submodule alternatives, release branches, a release table, or per-file hashes.
- DRM, access enforcement after download, or a claim that revocation can recall copies.
- Automatic repository creation for non-GitHub hosts in the first implementation.
- Proving the semantic safety, truth, or copyright status of Pack content without human review.

## Rollout Sequence

1. Approve this specification and its lifecycle-level test seam.
2. Implement Tasks 1-8 in LBrain Kit using only local fixtures and temporary Git repositories.
3. Review and release the resulting Kit version separately.
4. In a later phase, snapshot and migrate the user's personal LBrain to the released Kit structure.
5. Establish and verify the private LBrain remote.
6. Build and semantically review the first real Candidate.
7. Explicitly approve creation of the first public Pack repository.
8. Publish the Pack, add it as a Submodule, and commit the pointer in the private LBrain.

## Further Notes

- Public Pack repositories may be freely cloned or fed directly to agents. That portability is intentional.
- A Submodule does not make the child private or reveal its private parent. Repository permissions remain independent.
- `.gitmodules` reveals Pack names and remote URLs only to readers of the private LBrain repository.
- Personal LBrain migration and private-remote setup are later rollout concerns and must not be changed as part of this specification or the first Kit implementation phase.
- The design frontier is closed. Any implementation departure from this document requires an explicit review rather than a silent assumption.
