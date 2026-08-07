from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TRACER = ROOT / "System/Kit/Examples/Tracer/run.py"
CONTEXT_PACK_TRACER = ROOT / "System/Kit/Examples/Context-Pack/run.py"


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout.strip()


class WorkflowSmokeTest(unittest.TestCase):
    def test_capture_weave_retrieve_tracer(self) -> None:
        result = subprocess.run(
            [sys.executable, str(TRACER)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("TRACE PASS", result.stdout)

    def test_context_pack_intake_to_consumer_tracer(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CONTEXT_PACK_TRACER)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("INTAKE sources=git,notion,zulip,gmail", result.stdout)
        self.assertIn("PREVIEW blocked=0", result.stdout)
        self.assertIn("CONSUME git=unavailable", result.stdout)
        self.assertIn("CONTEXT PACK TRACE PASS", result.stdout)

    def test_release_upgrade_preserves_personal_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            kit = base / "kit-source"
            personal = base / "personal"
            private_origin = base / "private-origin.git"
            shutil.copytree(ROOT, kit, ignore=shutil.ignore_patterns(".git", "__pycache__"))

            git(kit, "init", "-b", "main")
            git(kit, "config", "user.name", "LBrain Test")
            git(kit, "config", "user.email", "lbrain-test@example.invalid")
            (kit / "System/Kit/VERSION").write_text("0.1.0\n", encoding="utf-8")
            git(kit, "add", ".")
            git(kit, "commit", "-m", "kit: release 0.1.0")
            git(kit, "tag", "v0.1.0")

            subprocess.run(["git", "init", "--bare", str(private_origin)], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(kit), str(personal)], check=True, capture_output=True)
            git(personal, "config", "user.name", "LBrain User")
            git(personal, "config", "user.email", "lbrain-user@example.invalid")
            git(personal, "remote", "rename", "origin", "kit")
            git(personal, "remote", "set-url", "--push", "kit", "DISABLED")
            git(personal, "branch", "-m", "main", "kit-base")
            git(personal, "switch", "-c", "main", "v0.1.0")
            git(personal, "remote", "add", "origin", str(private_origin))

            with (personal / "HOME.md").open("a", encoding="utf-8") as file:
                file.write("\nPersonal home marker.\n")
            with (personal / "Context/Identity/Profile.md").open("a", encoding="utf-8") as file:
                file.write("\nPersonal identity marker.\n")
            (personal / "Knowledge/Sources/Upgrade-Source.md").write_text(
                "---\ntype: source\nsummary: Synthetic upgrade source.\nstatus: active\nvisibility: private\norigin: synthetic\ncapture: reference\nweaving: woven\ncreated: 2026-08-07\nupdated: 2026-08-07\n---\n# Upgrade Source\n",
                encoding="utf-8",
            )
            (personal / "Knowledge/Wiki/Concepts/Personal-Upgrade-Note.md").write_text(
                "---\ntype: knowledge\nkind: concept\nsummary: Personal content that must survive an upgrade.\nstatus: active\nvisibility: private\nsources:\n  - \"[[Knowledge/Sources/Upgrade-Source]]\"\ncreated: 2026-08-07\nupdated: 2026-08-07\n---\n# Personal Upgrade Note\n\n[[Knowledge/Sources/Upgrade-Source]]\n",
                encoding="utf-8",
            )
            personal_skill = personal / "Skills/Personal/personal-upgrade"
            (personal_skill / "tests").mkdir(parents=True)
            (personal_skill / "SKILL.md").write_text(
                "---\nname: personal-upgrade\ndescription: Preserves a synthetic Personal Skill during upgrade tests.\nversion: 1.0.0\nstatus: active\nvisibility: private\ncreated: 2026-08-07\nupdated: 2026-08-07\n---\n# Personal Upgrade\n\nPreserve this skill. See `tests/cases.md`.\n",
                encoding="utf-8",
            )
            (personal_skill / "tests/cases.md").write_text("# Cases\n\n- Preserve the package.\n", encoding="utf-8")
            with (personal / "Skills/Enabled.md").open("a", encoding="utf-8") as file:
                file.write("\n- [[Skills/Personal/personal-upgrade/SKILL]] — codex, claude, hermes\n")

            pack_source = base / "personal-pack-source"
            pack_remote = base / "personal-pack.git"
            pack_path = "Outputs/Context-Packs/Repos/personal-pack"
            pack_source.mkdir()
            git(pack_source, "init", "-b", "main")
            git(pack_source, "config", "user.name", "LBrain User")
            git(pack_source, "config", "user.email", "lbrain-user@example.invalid")
            (pack_source / "PACK.md").write_text(
                "---\n"
                "type: context-pack-release\n"
                "pack_id: personal-pack\n"
                "summary: Personal Pack preserved by the upgrade test.\n"
                "version: 2026.08.07.1\n"
                "release_status: published\n"
                "visibility: private\n"
                "license: UNLICENSED\n"
                "created: 2026-08-07\n"
                "updated: 2026-08-07\n"
                "---\n# Personal Pack\n",
                encoding="utf-8",
            )
            (pack_source / "SOURCES.md").write_text("# Sources\n\nSynthetic upgrade fixture.\n", encoding="utf-8")
            git(pack_source, "add", ".")
            git(pack_source, "commit", "-m", "pack: publish personal-pack 2026.08.07.1")
            git(pack_source, "tag", "2026.08.07.1")
            pack_head = git(pack_source, "rev-parse", "HEAD")
            subprocess.run(["git", "clone", "--bare", str(pack_source), str(pack_remote)], check=True, capture_output=True)

            definition = personal / "Outputs/Context-Packs/personal-pack.md"
            definition.write_text(
                "---\n"
                "type: context-pack\n"
                "pack_id: personal-pack\n"
                "summary: Personal Pack preserved by the upgrade test.\n"
                "status: active\n"
                "visibility: private\n"
                f"repository: {pack_remote}\n"
                f"submodule_path: {pack_path}\n"
                "created: 2026-08-07\n"
                "updated: 2026-08-07\n"
                "---\n# Personal Pack\n\n"
                "## Purpose\n\nUpgrade preservation.\n\n"
                "## Includes\n\n- `path:Knowledge/Wiki/Concepts/Personal-Upgrade-Note.md`\n\n"
                "## Excludes\n\n- None.\n\n"
                "## Skills\n\n- None.\n\n"
                "## Build Notes\n\nSynthetic fixture.\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "protocol.file.allow=always",
                    "-C",
                    str(personal),
                    "submodule",
                    "add",
                    str(pack_remote),
                    pack_path,
                ],
                check=True,
                capture_output=True,
            )
            git(personal, "add", ".")
            git(personal, "commit", "-m", "capture: personalize upgrade fixture")

            (kit / "System/Kit/VERSION").write_text("0.1.1\n", encoding="utf-8")
            with (kit / "System/Rules/Core/visibility.md").open("a", encoding="utf-8") as file:
                file.write("\nUpgrade marker: v0.1.1.\n")
            (kit / "System/Kit/MIGRATIONS/0.1.0-to-0.1.1.md").write_text(
                "<!-- ownership: kit -->\n# 0.1.0 to 0.1.1\n\nNo user-owned files are changed.\n",
                encoding="utf-8",
            )
            git(kit, "add", ".")
            git(kit, "commit", "-m", "kit: release 0.1.1")
            git(kit, "tag", "v0.1.1")

            git(personal, "fetch", "kit", "--tags")
            git(personal, "switch", "kit-base")
            git(personal, "merge", "--ff-only", "kit/main")
            git(personal, "switch", "main")
            git(personal, "merge", "--no-ff", "v0.1.1", "-m", "kit: upgrade to v0.1.1")

            checked = subprocess.run(
                [sys.executable, str(personal / "System/Kit/check.py"), "--root", str(personal)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            self.assertIn("Personal home marker", (personal / "HOME.md").read_text(encoding="utf-8"))
            self.assertIn("Personal identity marker", (personal / "Context/Identity/Profile.md").read_text(encoding="utf-8"))
            self.assertTrue((personal / "Knowledge/Wiki/Concepts/Personal-Upgrade-Note.md").is_file())
            self.assertTrue((personal / "Skills/Personal/personal-upgrade/SKILL.md").is_file())
            self.assertIn("Upgrade marker: v0.1.1", (personal / "System/Rules/Core/visibility.md").read_text(encoding="utf-8"))
            self.assertTrue(definition.is_file())
            self.assertIn(str(pack_remote), (personal / ".gitmodules").read_text(encoding="utf-8"))
            self.assertIn("personal-pack", git(personal, "submodule", "status"))
            self.assertIn(pack_head, git(personal, "ls-tree", "HEAD", pack_path))


if __name__ == "__main__":
    unittest.main()
