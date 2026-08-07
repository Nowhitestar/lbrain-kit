<!-- ownership: kit -->
# Context Packs

Pack Definitions select private LBrain material for a portable, independently versioned release. Definitions are user-owned Markdown notes stored directly in this directory.

- Create Definitions from [[System/Templates/Core/context-pack]].
- Keep generated Candidates under `Candidates/`; they are rebuildable and ignored by the parent Git repository.
- Keep published Pack repositories under `Repos/`; each is an independent Git Submodule.
- Start with preview. Building does not authorize publication, and publication always requires explicit approval.
- LBrain remains canonical. Change canonical context or the Definition, then rebuild the Pack.

See [[System/Kit/CONTEXT_PACK_SPEC]] for the complete contract.
