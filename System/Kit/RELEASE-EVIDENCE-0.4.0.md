<!-- ownership: kit -->
# LBrain Kit 0.4.0 Release Evidence

Date: 2026-08-10

## Private dogfood (redacted)

- One real private non-code Project completed Profile preview/apply and a complete baseline Intake in an isolated copy; all required sources were read and the complete checkpoint advanced.
- One real saved article was correctly reused by legacy `origin` instead of duplicated; its existing Wiki weave was verified.
- The woven evidence produced one relevant Personal Skill Proposal, a validated exact minor-version preview, and an approved application in the isolated copy.
- Kit validation passed after both flows. The isolated copy was deleted, and no canonical private Project, Source, Wiki, Proposal, or Personal Skill was changed.

## Public verification

- Personal Intelligence tracer: Project Setup, partial and complete Intake, Source capture, Weave, Skill Proposal, exact preview, approved apply, runtime refresh, retrieval, and idempotent rerun.
- Runtime regression: Codex, Claude Code, Hermes, and OpenClaw installation behavior.
- Upgrade regression: a repository snapshot from the real `v0.3.0` tag preserves personalized Project/Intake Profile, runtime configuration, Knowledge, Personal Skill, and Context Pack state after the v0.4.0 merge.
- Atomic-operation regression: preview/apply hashes, partial state, deduplication, extraction failure, secret rejection, negative proposals, semantic versioning, stale preview rejection, runtime refresh, rollback, and replay.

## Final local verification

- `python3 -m unittest discover -s System/Kit/tests -p 'test_*.py'`: 49 tests passed.
- Current Codex `quick_validate.py`: Capture, Weave, and Skill Manager packages passed.
- `python3 System/Kit/check.py`: 0 errors and 0 warnings.
- `git diff --check`: passed.

## Release boundary

This evidence covers only the public, Kit-owned contents of v0.4.0. Publication requires separate explicit authorization. It does not authorize Pack publication or private-content publication.
