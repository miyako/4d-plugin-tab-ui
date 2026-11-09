import contextlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import release
import source_version as source


@contextlib.contextmanager
def cwd(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def git(path, *args):
    location = ["--git-dir", str(path)] if path.name.endswith(".git") else ["-C", str(path)]
    return subprocess.run(
        ["git", *location, *args], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def copy_source(destination):
    for path in source.SOURCE_PATHS:
        (destination / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, destination / path)


def entry(tag="v999.998.997", draft=False):
    return {"id": 42, "tag_name": tag, "draft": draft, "prerelease": False}


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        copy_source(self.root)
        self.current = source.read(self.root)

    def plist(self, **values):
        path = self.root / source.PLIST
        data = plistlib.loads(path.read_bytes())
        data.update(values)
        path.write_bytes(plistlib.dumps(data))

    def test_all_bump_modes_and_absent_keys(self):
        parts = list(map(int, self.current.split(".")))
        for mode, expected in (
            ("patch", [parts[0], parts[1], parts[2] + 1]),
            ("minor", [parts[0], parts[1] + 1, 0]),
            ("major", [parts[0] + 1, 0, 0]),
        ):
            with self.subTest(mode=mode):
                copy_source(self.root)
                self.assertNotIn("CFBundleVersion", plistlib.loads(
                    (self.root / source.PLIST).read_bytes()))
                new = ".".join(map(str, expected))
                self.assertEqual(source.bump(mode, self.root), new)
                self.assertEqual(source.read(self.root), new)
                self.assertNotIn("CFBundleVersion", plistlib.loads(
                    (self.root / source.PLIST).read_bytes()))

    def test_invalid_missing_and_drifted_project_settings(self):
        path = self.root / source.PROJECT
        original = path.read_text()
        for key in source.KEYS:
            for bad in ("1.2", "v1.2.3", "01.2.3", "1.2.3-beta", "$(UNKNOWN)", "", "0.0.0"):
                with self.subTest(key=key, bad=bad):
                    path.write_text(original.replace(f"{key} = {self.current};",
                                                     f"{key} = {bad};", 1))
                    with self.assertRaises(ValueError):
                        source.bump("patch", self.root)
            path.write_text(original.replace(f"{key} = {self.current};", "", 1))
            with self.assertRaises(ValueError):
                source.read(self.root)

    def test_plist_invalid_drift_missing_and_wrong_type(self):
        for key in ("CFBundleShortVersionString", "CFBundleVersion"):
            for value in ("0.0.0", "$(UNKNOWN)", "$(PRODUCT_NAME)", "", "1.2", 123):
                with self.subTest(key=key, value=value):
                    copy_source(self.root)
                    self.plist(**{key: value})
                    with self.assertRaises(ValueError):
                        source.read(self.root)
        path = self.root / source.PLIST
        path.write_bytes(plistlib.dumps({}))
        with self.assertRaises(ValueError):
            source.read(self.root)
        path.write_bytes(plistlib.dumps([]))
        with self.assertRaises(ValueError):
            source.read(self.root)

    def test_refs_preserved_and_optional_bundle_version_coordinated(self):
        for reference in source.REFERENCES:
            with self.subTest(reference=reference):
                copy_source(self.root)
                self.plist(CFBundleShortVersionString=reference, CFBundleVersion=reference)
                path = self.root / source.PROJECT
                path.write_text(path.read_text().replace(
                    f"CURRENT_PROJECT_VERSION = {self.current};",
                    'CURRENT_PROJECT_VERSION = "$(MARKETING_VERSION)";'
                ))
                new = source.bump("patch", self.root)
                data = plistlib.loads((self.root / source.PLIST).read_bytes())
                self.assertEqual(data["CFBundleShortVersionString"], reference)
                self.assertEqual(data["CFBundleVersion"], reference)
                self.assertEqual(path.read_text().count('"$(MARKETING_VERSION)"'), 6)
                self.assertEqual(source.read(self.root), new)
        copy_source(self.root)
        self.plist(CFBundleVersion=self.current)
        new = source.bump("minor", self.root)
        self.assertEqual(plistlib.loads((self.root / source.PLIST).read_bytes())["CFBundleVersion"], new)

    def test_cyclic_current_project_reference_rejected(self):
        path = self.root / source.PROJECT
        path.write_text(path.read_text().replace(
            f"CURRENT_PROJECT_VERSION = {self.current};",
            'CURRENT_PROJECT_VERSION = "$(CURRENT_PROJECT_VERSION)";'
        ))
        with self.assertRaises(ValueError):
            source.read(self.root)

    def test_localized_validation_and_preserved_encoding(self):
        path = self.root / source.LOCALIZED
        original = path.read_text(encoding="utf-8-sig")
        for malformed in (
            original.replace(f'CFBundleShortVersionString = "{self.current}"',
                             'CFBundleShortVersionString = "1.0"'),
            original.replace(f"tab-ui version {self.current},", "tab-ui version invalid,"),
            original + f'\nCFBundleShortVersionString = "{self.current}";\n',
            original.replace("CFBundleShortVersionString", "UnknownKey"),
        ):
            path.write_text(malformed)
            with self.assertRaises(ValueError):
                source.read(self.root)
        for newline in ("\n", "\r\n", "\r"):
            for encoding in ("utf-8", "utf-8-sig"):
                with self.subTest(newline=newline, encoding=encoding):
                    copy_source(self.root)
                    path.write_bytes(original.replace("\n", newline).encode(encoding))
                    new = source.bump("minor", self.root)
                    self.assertIn(f"tab-ui version {new}, Copyright 2019 miyako.",
                                  path.read_text(encoding="utf-8-sig"))
                    self.assertEqual(path.read_bytes().startswith(b"\xef\xbb\xbf"),
                                     encoding == "utf-8-sig")
                    self.assertEqual(path.read_bytes().decode(encoding).count(newline),
                                     original.count("\n"))

    def test_prebuilt_dependency_and_schema_metadata_untouched(self):
        excluded = self.root / "test/Plugins/tab-ui.bundle/Contents/Info.plist"
        excluded.parent.mkdir(parents=True)
        excluded.write_text("prebuilt 0.0.0")
        (self.root / "manifest.json").write_text('{"id": 20000}')
        source.bump("major", self.root)
        self.assertEqual(excluded.read_text(), "prebuilt 0.0.0")
        self.assertEqual((self.root / "manifest.json").read_text(), '{"id": 20000}')


class AvailabilityTests(unittest.TestCase):
    def test_paginated_draft_and_published_conflicts(self):
        for draft in (True, False):
            with self.subTest(draft=draft), patch.object(release, "remote_ref", return_value=None), \
                    patch.object(release, "api", side_effect=[
                        [entry()] * 100, [entry("v1.2.3", draft)]
                    ]) as api:
                with self.assertRaisesRegex(ValueError, "draft or published"):
                    release.available("owner/repo", "v1.2.3")
                self.assertEqual(api.call_args_list[1].args[0],
                                 "repos/owner/repo/releases?per_page=100&page=2")

    def test_complete_no_match_required(self):
        with patch.object(release, "remote_ref", return_value=None), \
                patch.object(release, "api", side_effect=[[entry()] * 100, []]) as api:
            release.available("owner/repo", "v1.2.3")
            self.assertEqual(api.call_count, 2)

    def test_errors_on_every_page_fail_closed(self):
        for page in (1, 2):
            for error in (*(subprocess.CalledProcessError(1, ["gh", "api", str(status)])
                            for status in (401, 403, 404, 500)),
                          OSError("network"), json.JSONDecodeError("bad", "?", 0)):
                with self.subTest(page=page, error=error), \
                        patch.object(release, "remote_ref", return_value=None), \
                        patch.object(release, "api", side_effect=(
                            [[entry()] * 100] * (page - 1) + [error])):
                    with self.assertRaises((ValueError, OSError, subprocess.CalledProcessError)):
                        release.available("owner/repo", "v1.2.3")

    def test_malformed_page_and_entry_schema(self):
        bad_pages = [{}, None, "[]", [None], [{}], [dict(entry(), id=True)],
                     [dict(entry(), tag_name=None)], [dict(entry(), draft="false")],
                     [dict(entry(), prerelease=None)], [entry()] * 101]
        for page in (1, 2):
            for bad in bad_pages:
                with self.subTest(page=page, bad=bad), \
                        patch.object(release, "remote_ref", return_value=None), \
                        patch.object(release, "api", side_effect=(
                            [[entry()] * 100] * (page - 1) + [bad])):
                    with self.assertRaises(ValueError):
                        release.available("owner/repo", "v1.2.3")

    def test_tag_and_remote_errors_block(self):
        with patch.object(release, "remote_ref", return_value="a" * 40), \
                patch.object(release, "api") as api:
            with self.assertRaises(ValueError):
                release.available("owner/repo", "v1.2.3")
            api.assert_not_called()
        for output in ("not-a-sha\trefs/tags/v1.2.3", "a" * 40,
                       "a" * 40 + "\trefs/tags/wrong",
                       ("a" * 40 + "\trefs/tags/v1.2.3\n") * 2):
            with patch.object(release, "run", return_value=output), self.assertRaises(ValueError):
                release.remote_ref("refs/tags/v1.2.3")
        with patch.object(release, "run", side_effect=OSError("network")), \
                patch.object(release, "api") as api:
            with self.assertRaises(OSError):
                release.available("owner/repo", "v1.2.3")
            api.assert_not_called()

    def test_api_transport_explicit_get_post_no_retry(self):
        with patch.object(release, "run", return_value="[]") as run:
            release.api("repos/o/r/releases?per_page=100&page=2")
            self.assertEqual(run.call_args.args,
                             ("gh", "api", "--method", "GET",
                              "repos/o/r/releases?per_page=100&page=2"))
        with patch.object(release, "run", return_value='{"id": 7}') as run:
            payload = {"tag_name": "v1.2.3", "draft": False}
            release.api("repos/o/r/releases", payload)
            self.assertIn("POST", run.call_args.args)
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), payload)
            asset = Path("tab-ui-1.2.3.zip")
            endpoint = "https://uploads.github.com/repos/o/r/releases/123/assets?name=tab-ui-1.2.3.zip"
            release.api(endpoint, asset=asset)
            self.assertEqual(run.call_args.args, (
                "gh", "api", "--method", "POST", endpoint,
                "--header", "Content-Type: application/octet-stream", "--input", str(asset),
            ))
        with patch.object(release, "run", side_effect=subprocess.CalledProcessError(1, "gh")) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                release.api("repos/o/r/releases")
            self.assertEqual(run.call_count, 1)


class GitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.local = self.root / "local"
        self.peer = self.root / "peer"
        git(self.root, "init", "--bare", str(self.remote))
        git(self.root, "init", "-b", "selected", str(self.local))
        for key, value in (("user.name", "Lifecycle Test"), ("user.email", "test@example.invalid"),
                           ("push.followTags", "true")):
            git(self.local, "config", key, value)
        git(self.local, "commit", "--allow-empty", "-m", "ancestor")
        self.ancestor = git(self.local, "rev-parse", "HEAD")
        copy_source(self.local)
        shutil.copytree(ROOT / ".github/scripts", self.local / ".github/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / ".gitignore", self.local / ".gitignore")
        git(self.local, "add", ".")
        git(self.local, "commit", "-m", "fixture")
        git(self.local, "remote", "add", "origin", str(self.remote))
        git(self.local, "push", "origin", "HEAD:refs/heads/selected")
        self.sha = git(self.local, "rev-parse", "HEAD")
        self.version = source.read(self.local)
        self.tag = f"v{self.version}"
        self.published = None
        self.uploaded = []
        git(self.root, "clone", "--branch", "selected", str(self.remote), str(self.peer))
        git(self.peer, "config", "user.name", "Peer")
        git(self.peer, "config", "user.email", "peer@example.invalid")
        self.enter = cwd(self.local)
        self.enter.__enter__()
        self.addCleanup(self.enter.__exit__, None, None, None)
        self.hooks = patch.object(release, "__file__", str(self.local / ".github/scripts/release.py"))
        self.hooks.start()
        self.addCleanup(self.hooks.stop)

    def advance_peer(self):
        (self.peer / "peer.txt").write_text("concurrent branch update")
        git(self.peer, "add", ".")
        git(self.peer, "commit", "-m", "peer")
        git(self.peer, "push", "origin", "HEAD:refs/heads/selected")

    def test_bump_selected_branch_disables_follow_tags(self):
        git(self.local, "tag", "-a", "unrelated-annotated", "-m", "must not follow")
        git(self.remote, "update-ref", "refs/heads/other", self.sha)
        release.bump_branch(self.sha, "selected", "patch")
        self.assertNotEqual(git(self.remote, "rev-parse", "refs/heads/selected"), self.sha)
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/other"), self.sha)
        self.assertEqual(git(self.remote, "tag", "--list"), "")
        self.assertEqual(set(git(self.local, "diff-tree", "--no-commit-id", "--name-only",
                                 "-r", "HEAD").splitlines()), set(map(str, source.SOURCE_PATHS)))
        self.assertEqual(git(self.local, "status", "--porcelain"), "")

    def test_bump_cli_bytecode_keeps_clean_checkout(self):
        env = os.environ.copy()
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        subprocess.run(
            [sys.executable, ".github/scripts/release.py", "bump", "--sha", self.sha,
             "--branch", "selected", "--mode", "patch"],
            env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(git(self.local, "status", "--porcelain"), "")
        self.assertNotEqual(git(self.remote, "rev-parse", "refs/heads/selected"), self.sha)
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_immutable_sha_dirty_checkout_and_bad_branch(self):
        for sha in ("selected", "a" * 40, "a" * 39, "a" * 41):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                release.selected_sha(sha)
        release.selected_sha(self.sha)
        with self.assertRaises(subprocess.CalledProcessError):
            release.bump_branch(self.sha, "bad..branch", "patch")
        (self.local / "dirty").write_text("dirty")
        with self.assertRaisesRegex(ValueError, "clean"):
            release.bump_branch(self.sha, "selected", "patch")
        with self.assertRaisesRegex(ValueError, "clean"):
            release.preflight(self.sha)

    def test_branch_races_before_and_during_preparation(self):
        real_bump = release.bump
        def concurrent_bump(mode):
            result = real_bump(mode)
            self.advance_peer()
            return result
        with patch.object(release, "bump", side_effect=concurrent_bump):
            with self.assertRaisesRegex(ValueError, "moved during"):
                release.bump_branch(self.sha, "selected", "minor")
        self.assertEqual(release.remote_ref("refs/heads/selected"), git(self.peer, "rev-parse", "HEAD"))
        git(self.local, "switch", "--detach", self.sha)
        with self.assertRaisesRegex(ValueError, "moved since"):
            release.bump_branch(self.sha, "selected", "patch")

    def advertised_race(self, kind):
        real_run = release.run
        expected = None
        pushes = 0
        checks = 0
        def concurrent_push(*args, **kwargs):
            nonlocal expected, pushes, checks
            if "ls-remote" in args:
                checks += 1
            if "push" in args:
                self.assertEqual(checks, 2)  # Precisely after the final ls-remote.
                pushes += 1
                if kind == "rewind":
                    expected = self.ancestor
                    git(self.remote, "update-ref", "refs/heads/selected", expected)
                elif kind == "delete":
                    git(self.remote, "update-ref", "-d", "refs/heads/selected")
                elif kind == "advance":
                    self.advance_peer()
                    expected = git(self.peer, "rev-parse", "HEAD")
                elif kind == "same-result":
                    expected = git(self.local, "rev-parse", "HEAD")
                    git(self.remote, "fetch", "--no-tags", str(self.local), "HEAD")
                    git(self.remote, "update-ref", "refs/heads/selected", expected)
            return real_run(*args, **kwargs)
        with patch.object(release, "run", side_effect=concurrent_push):
            with self.assertRaises(subprocess.CalledProcessError):
                release.bump_branch(self.sha, "selected", "patch")
        self.assertEqual(pushes, 1)
        self.assertEqual(release.remote_ref("refs/heads/selected"), expected)
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_advertised_branch_rewind(self):
        self.advertised_race("rewind")

    def test_advertised_branch_deletion(self):
        self.advertised_race("delete")

    def test_advertised_branch_advance(self):
        self.advertised_race("advance")

    def test_advertised_same_result(self):
        self.advertised_race("same-result")

    def test_missing_or_nonexecutable_guard_fails_closed(self):
        guard = self.local / ".github/scripts/bump-hooks/pre-push"
        guard.chmod(0o644)
        for absent in (False, True):
            if absent:
                guard.unlink()
            with self.subTest(absent=absent), self.assertRaisesRegex(ValueError, "guard"):
                release.bump_branch(self.sha, "selected", "patch")
            self.assertEqual(git(self.local, "rev-parse", "HEAD"), self.sha)
            self.assertEqual(release.remote_ref("refs/heads/selected"), self.sha)

    def assets(self):
        paths = [Path(f"tab-ui-{self.version}.{ext}") for ext in ("zip", "dmg")]
        for asset in paths:
            asset.write_bytes(b"fixture asset")
        return paths

    def publication_api(self, calls, fail=None, race=None):
        def api(endpoint, payload=None, asset=None):
            calls.append((endpoint, payload, asset))
            if "/releases?" in endpoint:
                return []
            if endpoint.endswith("/git/refs"):
                if race:
                    git(self.remote, "update-ref", f"refs/tags/{self.tag}", race)
                # Model GitHub POST git/refs with real atomic create-only bare Git.
                git(self.remote, "update-ref", payload["ref"], payload["sha"], "0" * 40)
                return {"ref": payload["ref"], "object": {"sha": payload["sha"]}}
            if endpoint.endswith("/releases"):
                if fail == "release":
                    raise subprocess.CalledProcessError(1, ["gh", "api"])
                self.published = {"id": 123, "tag_name": self.tag, "draft": False, "prerelease": False}
                return self.published
            if asset is not None:
                if fail == asset.suffix:
                    raise subprocess.CalledProcessError(1, ["gh", "api"])
                self.uploaded.append(asset.name)
                return {"id": 456, "name": asset.name,
                        "size": asset.stat().st_size, "state": "uploaded"}
            raise AssertionError(endpoint)
        return api

    def test_publication_create_only_exact_sha_and_new_release_id(self):
        calls = []
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls)):
            release.publish(self.sha, self.assets())
        self.assertEqual(git(self.remote, "rev-parse", f"refs/tags/{self.tag}"), self.sha)
        self.assertIn("/releases?", calls[0][0])
        self.assertTrue(calls[1][0].endswith("/git/refs"))
        self.assertEqual(calls[2][1], {
            "tag_name": self.tag, "target_commitish": self.sha, "name": self.tag,
            "draft": False, "prerelease": False, "body": "",
        })
        self.assertEqual(len(calls), 5)
        for endpoint, payload, asset in calls[3:]:
            self.assertIn("/releases/123/assets?name=", endpoint)
            self.assertIsNone(payload)
            self.assertIsNotNone(asset)

    def test_same_sha_tag_creation_race(self):
        calls = []
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls, race=self.sha)):
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish(self.sha, self.assets())
        self.assertEqual(len(calls), 2)
        self.assertEqual(git(self.remote, "rev-parse", f"refs/tags/{self.tag}"), self.sha)

    def test_different_sha_tag_creation_race(self):
        calls = []
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls, race=self.ancestor)):
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish(self.sha, self.assets())
        self.assertEqual(len(calls), 2)
        self.assertEqual(git(self.remote, "rev-parse", f"refs/tags/{self.tag}"), self.ancestor)

    def test_release_post_failure_retains_tag(self):
        calls = []
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls, fail="release")):
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish(self.sha, self.assets())
        self.assertEqual(len(calls), 3)
        self.assertEqual(git(self.remote, "rev-parse", f"refs/tags/{self.tag}"), self.sha)
        self.assertIsNone(self.published)
        self.assertEqual(self.uploaded, [])

    def test_upload_failure_retains_release_and_prior_asset(self):
        calls = []
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls, fail=".dmg")):
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish(self.sha, self.assets())
        self.assertEqual(len(calls), 5)
        self.assertEqual(git(self.remote, "rev-parse", f"refs/tags/{self.tag}"), self.sha)
        self.assertEqual(self.published["id"], 123)
        self.assertEqual(self.uploaded, [f"tab-ui-{self.version}.zip"])

    def test_final_recheck_blocks_new_draft(self):
        calls = []
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls)):
            release.preflight(self.sha)
        paths = self.assets()
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", return_value=[entry(self.tag, True)]) as api:
            with self.assertRaisesRegex(ValueError, "draft or published"):
                release.publish(self.sha, paths)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_tag_sha_verification_blocks_release(self):
        calls = []
        real_remote_ref = release.remote_ref
        def incorrect_verification(ref):
            return "a" * 40 if real_remote_ref(ref) else None
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=self.publication_api(calls)), \
                patch.object(release, "remote_ref", side_effect=incorrect_verification):
            with self.assertRaisesRegex(ValueError, "exact-SHA verification"):
                release.publish(self.sha, self.assets())
        self.assertEqual(len(calls), 2)
        self.assertIsNone(self.published)

    def test_malformed_release_post_response_retains_state(self):
        calls = []
        real_api = self.publication_api(calls)
        def malformed_release(endpoint, payload=None, asset=None):
            result = real_api(endpoint, payload, asset)
            return {"id": "not-an-integer"} if endpoint.endswith("/releases") else result
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=malformed_release):
            with self.assertRaisesRegex(ValueError, "Malformed create-release response"):
                release.publish(self.sha, self.assets())
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.published["id"], 123)
        self.assertEqual(self.uploaded, [])
        self.assertEqual(git(self.remote, "rev-parse", f"refs/tags/{self.tag}"), self.sha)

    def test_malformed_upload_response_retains_state(self):
        calls = []
        real_api = self.publication_api(calls)
        def malformed_upload(endpoint, payload=None, asset=None):
            result = real_api(endpoint, payload, asset)
            return {"id": None} if asset is not None else result
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", side_effect=malformed_upload):
            with self.assertRaisesRegex(ValueError, "Malformed upload response"):
                release.publish(self.sha, self.assets())
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.published["id"], 123)
        self.assertEqual(self.uploaded, [f"tab-ui-{self.version}.zip"])
        self.assertEqual(git(self.remote, "rev-parse", f"refs/tags/{self.tag}"), self.sha)

    def test_changed_source_after_preflight_blocks_publication(self):
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api", return_value=[]):
            release.preflight(self.sha)
        source.bump("patch")
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api") as api:
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish(self.sha, self.assets())
        api.assert_not_called()
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_missing_asset_fails_before_remote_mutation(self):
        with patch.dict(os.environ, GITHUB_REPOSITORY="owner/repo"), \
                patch.object(release, "api") as api:
            with self.assertRaises(ValueError):
                release.publish(self.sha, [Path(f"tab-ui-{self.version}.zip"),
                                           Path(f"tab-ui-{self.version}.dmg")])
        api.assert_not_called()
        self.assertEqual(git(self.remote, "tag", "--list"), "")


class WiringTests(unittest.TestCase):
    def test_manual_zero_input_immutable_gate_wiring(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertRegex(workflow, r"(?m)^name: Build$")
        self.assertEqual(workflow.split("on:\n", 1)[1].split("\npermissions:", 1)[0].strip(),
                         "workflow_dispatch:")
        self.assertEqual(workflow.count("uses: actions/checkout@v4"), 2)
        self.assertEqual(workflow.count("ref: ${{ github.sha }}"), 2)
        self.assertIn("group: release-publication\n  cancel-in-progress: false", workflow)
        self.assertNotIn("github.ref }}", workflow)
        self.assertNotIn("build-windows:", workflow)
        self.assertIn("needs: [version]", workflow)
        self.assertEqual(workflow.count("GH_TOKEN: ${{ github.token }}"), 2)
        gates = [
            "validate source version and publication availability",
            "import Developer ID certificate", "store notarytool credentials",
            "build macOS plugin (universal)", "verify universal binary", "- name: codesign",
            "package, notarize & staple", "recheck availability and create tag, release and assets",
        ]
        positions = [workflow.index(gate) for gate in gates]
        self.assertEqual(positions, sorted(positions))
        for required in ('ARCHS="arm64 x86_64"', "codesign --verify --deep --strict",
                         'stapler staple "$DMG_PATH"', 'notarytool submit "$ZIP_PATH"',
                         'notarytool submit "$DMG_PATH"', "APPLE_DEVELOPER_ID_CERTIFICATE",
                         "APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD", "KEYCHAIN_PASSWORD",
                         "NOTARYTOOL_APPLE_ID", "NOTARYTOOL_TEAM_ID", "NOTARYTOOL_PASSWORD",
                         'ZIP_PATH="${{ env.PRODUCT_NAME }}-${VERSION}.zip"',
                         'DMG_PATH="${{ env.PRODUCT_NAME }}-${VERSION}.dmg"'):
            self.assertIn(required, workflow)
        self.assertNotIn("continue-on-error", workflow)
        self.assertNotIn("always()", workflow)

    def test_bump_and_no_destructive_publication(self):
        workflow = (ROOT / ".github/workflows/bump-version.yml").read_text()
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn("SELECTED_BRANCH: ${{ github.ref_name }}", workflow)
        self.assertIn('test "$REF_TYPE" = branch', workflow)
        for mode in ("patch", "minor", "major"):
            self.assertIn(f"- {mode}", workflow)
        helper = (ROOT / ".github/scripts/release.py").read_text()
        for prohibited in ('"DELETE"', '"PATCH"', "--clobber", "--force",
                           '"gh", "release", "create"', '"git", "tag"'):
            self.assertNotIn(prohibited, helper)
        self.assertIn('"push.followTags=false"', helper)
        self.assertIn('"--no-follow-tags"', helper)
        self.assertNotIn("workflow_dispatch", helper)

    def test_publication_cli_accepts_assets_after_options(self):
        assets = [Path("tab-ui-1.2.3.zip"), Path("tab-ui-1.2.3.dmg")]
        with patch.object(sys, "argv", ["release.py", "publish", "--sha", "a" * 40,
                                       *map(str, assets)]), \
                patch.object(release, "publish") as publish:
            release.main()
        publish.assert_called_once_with("a" * 40, assets)


if __name__ == "__main__":
    unittest.main()
