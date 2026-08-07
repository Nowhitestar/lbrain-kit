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
git switch -c main v0.1.0-rc.1
```

`kit-base` follows the public Kit. `main` is the private personal context history. The disabled push URL prevents an accidental push of personal context to the public Kit.

For a private remote:

```sh
git remote add origin <private-repository-url>
git push -u origin main
```

A local-only LBrain may omit `origin`, but loses off-device backup. Confirm the remote is private before the first push.

## Personalize

1. Rewrite [[HOME]] and the seeded notes under [[Context/Identity/README|Identity]].
2. Keep the six Core Skills enabled in [[Skills/Enabled]].
3. Add local rules under [[System/Rules/Local/README|Local Rules]].
4. Run `python3 System/Kit/check.py`.
5. Commit the initialized personal baseline to `main`.

Runtime installation is optional. Preview first and always target a deliberate directory:

```sh
python3 Skills/Kit/lbrain-skill-manager/scripts/install.py --runtime codex --target <isolated-or-runtime-skill-directory> --dry-run
```

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

Before merging, read `CHANGELOG.md` and the release file under `MIGRATIONS/`. Resolve conflicts according to [[System/Kit/OWNERSHIP]]:

- accept Kit updates for Kit-owned files unless you intentionally fork the contract;
- preserve User-owned files;
- preserve personalized Seeded files and apply any suggested seeded change manually.

Do not push an upgrade until validation passes and the personal content diff is reviewed.

## Agent commit policy

An agent may commit an authorized, validated change locally. It must not push unless the user explicitly asks. Ordinary knowledge work happens on `main`; large migrations use a temporary branch merged after review.
