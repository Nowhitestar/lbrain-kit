<!-- ownership: kit -->
# Setup and Upgrade

LBrain Kit is initialized with Git and maintained through release tags. Replace placeholders in angle brackets; do not paste credentials into Git URLs or Markdown.

## Initialize from a Kit release

```sh
git clone <kit-repository-url> <your-lbrain-directory>
cd <your-lbrain-directory>
git remote rename origin kit
git remote set-url --push kit DISABLED
git branch -m main kit-base
git switch -c main v0.4.0
```

`kit-base` follows the public Kit. `main` is the private personal context history. The disabled push URL prevents an accidental push of personal context to the public Kit.

Clone the full Kit repository. Do not use a tag-only `--single-branch` clone: `kit-base` needs the `kit/main` reference even though personal `main` starts from a release tag.

For a private remote:

```sh
git remote add origin <private-repository-url>
git push -u origin main
```

A local-only LBrain may omit `origin`, but loses off-device backup. Confirm the remote is private before the first push.

## Personalize

1. Rewrite [[HOME]].
2. Personalize the seeded notes under [[Context/Identity/README|Identity]]. A user may edit their own Identity directly. An assisting agent must first present the exact Identity values in one initialization Proposal and apply them only after explicit acceptance; it must not infer missing identity from a general setup request.
3. Keep the seven Core Skills enabled in [[Skills/Enabled]].
4. Add local rules under [[System/Rules/Local/README|Local Rules]].
5. Run `python3 System/Kit/check.py`.
6. Commit the initialized personal baseline to `main`.

Runtime installation is optional. Preview first and always target a deliberate directory:

```sh
python3 Skills/Kit/lbrain-skill-manager/scripts/install.py --runtime codex --target <isolated-or-runtime-skill-directory> --dry-run
```

Rerunning the installer is safe: unchanged installed packages are skipped and newly enabled Skills are added. A divergent existing package stops the entire install before any write. Symlink installs follow canonical LBrain updates automatically; copy installs must be reviewed and replaced explicitly when their canonical package changes.

## Configure retrieval

Install qmd separately when hybrid local retrieval is desired. qmd is the recommended provider, not the source of truth. The filesystem fallback remains available without qmd.

Check the current provider from any directory:

```sh
python3 <installed-lbrain-retrieve>/scripts/retrieval.py register --root <your-lbrain-directory>
python3 <installed-lbrain-retrieve>/scripts/retrieval.py register --root <your-lbrain-directory> --apply
python3 <installed-lbrain-retrieve>/scripts/retrieval.py doctor --root <your-lbrain-directory>
```

The local root registry makes copy-installed runtimes such as OpenClaw independent of their starting directory. It contains only the canonical LBrain path and refuses to overwrite a different registration.

If no matching qmd index exists, preview and create a dedicated `lbrain` index configuration:

```sh
python3 <installed-lbrain-retrieve>/scripts/retrieval.py configure --root <your-lbrain-directory>
python3 <installed-lbrain-retrieve>/scripts/retrieval.py configure --root <your-lbrain-directory> --apply
python3 <installed-lbrain-retrieve>/scripts/retrieval.py update --root <your-lbrain-directory>
python3 <installed-lbrain-retrieve>/scripts/retrieval.py embed --root <your-lbrain-directory>
```

`configure` refuses to overwrite a divergent qmd configuration. Set `LBRAIN_QMD_BIN` to an absolute qmd wrapper when the default `qmd` executable uses an incompatible Node runtime. Set `LBRAIN_ROOT` for copy-mode installations used outside the LBrain tree.

MCP-capable runtimes should launch qmd through the adapter so the same index-selection and root checks apply:

```text
command: python3
args: [<installed-lbrain-retrieve>/scripts/retrieval.py, mcp, --root, <your-lbrain-directory>]
```

Exact client configuration examples and fallback behavior live in `Skills/Kit/lbrain-retrieve/references/providers.md`.

## Upgrade

Merge only formal Kit release tags into personal `main`:

```sh
git switch kit-base
git fetch kit --tags
git merge --ff-only kit/main
git switch main
git merge --no-ff v<release> -m "kit: upgrade to v<release>"
python3 System/Kit/check.py
```

If the selected personal release already registers Context Pack Submodules, restore them after the merge:

```sh
git submodule sync --recursive
git submodule update --init --recursive
```

Kit upgrades preserve user-owned Pack Definitions, `.gitmodules` registrations, and Submodule pointers. A temporarily unavailable Pack remote does not erase those records; restore access and rerun the Submodule update before using that Pack.

`kit-base` may move ahead of the latest release tag so the user can inspect upcoming Kit history. Never merge `kit-base` itself into personal `main`; merge only the exact formal release tag selected above.

Before merging, read `CHANGELOG.md` and the release file under `MIGRATIONS/`. Resolve conflicts according to [[System/Kit/OWNERSHIP]]:

- accept Kit updates for Kit-owned files unless you intentionally fork the contract;
- preserve User-owned files;
- preserve personalized Seeded files and apply any suggested seeded change manually.

The 0.2.0 migration requires preserving `Skills/Enabled.md` personalization while adding the seventh mandatory Core Skill entry. The 0.3.0 migration moves Skill lifecycle metadata into `lbrain.json` and optionally adds OpenClaw to personalized runtime selections. The 0.4.0 migration adds deterministic Personal Intelligence writes without requiring a bulk rewrite of existing Projects, Sources, Proposals, or Personal Skills. Later migrations state their own exact Seeded reconciliation, if any.

Do not push an upgrade until validation passes and the personal content diff is reviewed.

## Agent commit policy

An agent may commit an authorized, validated change locally. It must not push unless the user explicitly asks. Ordinary knowledge work happens on `main`; large migrations use a temporary branch merged after review.
