<!--
Sync Impact Report
==================
Version change: (none) -> 1.0.0
Rationale:      Initial ratification. No prior version existed; the
                constitution file was an unfilled template copied from
                .specify/templates/constitution-template.md. This commit
                adopts the canonical Spec Kit principles for the project.

Modified principles:  none (template -> first concrete version)
  - I.   Library-First                       (template -> same title)
  - II.  CLI Interface                       (template -> same title)
  - III. Test-First (NON-NEGOTIABLE)         (template -> same title)
  - IV.  Integration Testing                 (template -> same title)
  - V.   Observability, Versioning & Simplicity
                                              (template -> same title)

Added sections:
  - Additional Constraints                   (new)
  - Development Workflow                     (new)
  - Governance                               (template placeholder -> concrete)

Removed sections: none

Templates requiring updates:
  - .specify/templates/plan-template.md     OK — Constitution Check
        section is generic ("[Gates determined based on constitution
        file]") and continues to match the principles above.
  - .specify/templates/spec-template.md     OK — User-story / requirements
        structure is unaffected by principle adoption.
  - .specify/templates/tasks-template.md    OK — Phase 3+ test-first and
        parallel [P] task patterns already align with Principle III and
        Principle I.
  - .specify/templates/checklist-template.md OK — no principle-specific
        references.
  - .claude/skills/speckit-*/SKILL.md       OK — only the speckit-plan
        skill loads the constitution to fill its "Constitution Check"
        section, and does so generically.

Deferred items (placeholders intentionally retained):
  - TODO(TECH_STACK): the project language/runtime/framework is not yet
        chosen. Once a stack is selected, add a sentence to
        "Additional Constraints" describing it.
  - TODO(RATIFICATION_DATE): set to today's date as the initial adoption
        date; update only if a true prior adoption is discovered.

This Sync Impact Report is an HTML comment at the top of the file so it
is invisible to readers but preserved in version control.
-->

# Recommand Constitution

## Core Principles

### I. Library-First

Every feature starts as a standalone library. Libraries MUST be
self-contained, independently testable, and documented. Clear purpose is
required — no organizational-only libraries (libraries must solve a
real, named problem). Library boundaries drive module ownership and
reusability: a feature that cannot be expressed as a library is a
signal to revisit its scope.

### II. CLI Interface

Every library MUST expose its functionality via a CLI. Text in/out
protocol: stdin/args → stdout; errors → stderr. CLIs MUST support both
JSON and a human-readable output format. This guarantees debuggability
and makes every capability scriptable, testable, and composable from
CI.

### III. Test-First (NON-NEGOTIABLE)

TDD is mandatory and strictly enforced: tests are written first, the
user approves them, the tests are observed to fail, and only then is
implementation written to make them pass. The Red → Green → Refactor
cycle MUST be followed. No production code lands without a failing
test that it makes pass.

### IV. Integration Testing

Integration tests are required wherever contracts cross a boundary.
Focus areas: new library contract tests, contract changes, inter-service
communication, and shared schemas. Unit tests alone are insufficient to
prove a contract holds; the contract test is the executable
specification between producer and consumer.

### V. Observability, Versioning & Breaking Changes, Simplicity

These three rules govern non-functional behavior:

- **Observability**: Text I/O is the floor for debuggability; structured
  logging is required for any non-trivial operation. Logs and errors
  MUST be machine-parseable.
- **Versioning & Breaking Changes**: Public APIs and contracts use
  `MAJOR.MINOR.BUILD` semver. Any change that breaks a published
  contract MUST bump MAJOR and ship a migration note.
- **Simplicity**: Start simple. Apply YAGNI. Complexity MUST be
  justified in the plan's "Complexity Tracking" table, with the
  simpler alternative explicitly rejected and the reason recorded.

## Additional Constraints

- **Specification-driven delivery**: every feature flows through
  `spec.md → plan.md → tasks.md → implementation`; shortcuts are not
  permitted.
- **Independent user stories**: each prioritized user story in
  `spec.md` MUST be independently implementable, testable, and
  deployable.
- **Traceability**: every task in `tasks.md` MUST carry a `[Story]`
  label mapping it back to a user story in `spec.md`.
- TODO(TECH_STACK): language, runtime, and primary framework will be
  recorded here once chosen. Until then, principles above apply
  stack-agnostically.

## Development Workflow

1. **Specify** — run `/speckit-specify` to capture user stories,
   requirements, and success criteria in `spec.md`.
2. **Plan** — run `/speckit-plan` to produce `plan.md` with technical
   context, a Constitution Check, and project structure. The
   Constitution Check MUST pass before Phase 0 research begins and
   MUST be re-checked after Phase 1 design.
3. **Tasks** — run `/speckit-tasks` to decompose the plan into
   per-story, parallelizable tasks in `tasks.md`.
4. **Implement** — run `/speckit-implement` to execute tasks in
   dependency order, stopping at every per-story checkpoint to verify
   independent testability.
5. **Review** — run `/speckit-analyze` after implementation to detect
   drift across spec, plan, and code.
6. **Branch discipline**: each feature is a `[###-feature-name]`
   branch off `main`; merges to `main` happen via PR after Constitution
   Check and review pass.

## Governance

This constitution supersedes all other project practices. Amendments
require:

1. A documented proposal (in the PR description) describing the change
   and its rationale.
2. Approval by the project maintainer(s).
3. A migration plan whenever a principle change invalidates existing
   artifacts (specs, plans, code).

Versioning policy: `MAJOR` for backward-incompatible governance or
principle removals/redefinitions; `MINOR` for new principles or
materially expanded guidance; `PATCH` for clarifications, wording, and
typo fixes. The version line at the bottom of this file MUST be
updated in the same commit as the change.

Compliance review: every PR and review MUST verify the change against
the principles in this file. Violations of Principle III (Test-First)
or Principle I (Library-First) are blocking. Use `CLAUDE.md` for
runtime development guidance and `.specify/templates/` for the
authoritative document templates.

**Version**: 1.0.0 | **Ratified**: 2026-06-12 | **Last Amended**: 2026-06-12
