<!-- ownership: kit -->
# Context Packs

Pack Definitions select private LBrain material for a portable, independently versioned release. Definitions are user-owned Markdown notes stored directly in this directory.

- Create Definitions from [[System/Templates/Core/context-pack]].
- Keep generated Candidates under `Candidates/`; they are rebuildable and ignored by the parent Git repository.
- Keep published Pack repositories under `Repos/`; each is an independent Git Submodule.
- Start with preview. Building does not authorize publication, and publication always requires explicit approval.
- LBrain remains canonical. Change canonical context or the Definition, then rebuild the Pack.

See [[System/Kit/CONTEXT_PACK_SPEC]] for the complete contract.

## Owner workflow

Run the Core Skill script from the LBrain root. Paths below are repository-relative:

```sh
python3 Skills/Kit/lbrain-context-pack/scripts/pack.py create <pack-id> --summary "<purpose>" --visibility public --license MIT
python3 Skills/Kit/lbrain-context-pack/scripts/pack.py preview Outputs/Context-Packs/<pack-id>.md
python3 Skills/Kit/lbrain-context-pack/scripts/pack.py build Outputs/Context-Packs/<pack-id>.md
```

Preview and publication print a complete file diff with recognized secrets and private paths redacted. Review the Candidate itself for semantic sensitivity. Publication is a separate operation and requires explicit approval:

```sh
python3 Skills/Kit/lbrain-context-pack/scripts/pack.py publish Outputs/Context-Packs/<pack-id>.md --remote <empty-or-registered-pack-repository> --approve-publication
python3 Skills/Kit/lbrain-context-pack/scripts/pack.py verify Outputs/Context-Packs/<pack-id>.md
```

GitHub first publication uses two independent approvals: one to create the repository and one to publish the reviewed Candidate. If a push stops after remote `main` is created, the error prints the exact `--remote` resume boundary; the retry verifies matching content before completing the tag and parent registration. Existing releases use `update`; downloaded copies cannot be recalled, so `revoke` only publishes a forward warning release. `fork` creates a new independent Pack identity and history. Run each command with `--help` for its explicit approval flags.

An owner update is also two-step: run `update <definition>` to rebuild and inspect the diff, then rerun it with `--approve-publication`. A consumer runs `update <definition> --check-remote`; the command verifies remote `main`, the manifest, and its matching CalVer tag before offering `--approve-pointer`.

For a public Pack, every included Personal or imported third-party Skill needs an exact SPDX-style license declaration in `SKILL.md` and its own matching license file. The declared identifier must exactly equal the Pack license; unknown license texts need a matching `SPDX-License-Identifier` line near the top. A failed or uncertain match pauses publication for an explicit licensing decision.

## Recipient workflow

A recipient may clone the Pack repository or receive a downloaded directory. Start with `PACK.md`, follow its loading order, and load only the included `context/`, `knowledge/`, `skills/`, and `artifacts/` material needed for the task. Git enables release and integrity checks; without Git, the Pack remains usable and verification is structural only. LBrain is not required.
