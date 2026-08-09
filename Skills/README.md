<!-- ownership: kit -->
# Skills

Skills are canonical agent capability packages stored in LBrain. Runtime directories are installations, never the source of truth.

- [[Skills/Kit/README|Kit Skills]] are versioned with Kit releases.
- [[Skills/Personal/README|Personal Skills]] are user-owned and independently versioned.
- [[Skills/Enabled]] records what should be installed for each runtime.

Every package requires a portable `SKILL.md` containing only `name` and `description` frontmatter, plus an `lbrain.json` lifecycle sidecar. It may include `references/`, `scripts/`, `assets/`, and `examples/`. An active skill also requires `tests/cases.md` with trigger and behavior cases. See [[System/Kit/AGENT-RUNTIME#Portable Skill Contract]].
