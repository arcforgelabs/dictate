"""Rules for the dictate-* release workflows (docs/RELEASING.md).

Release jobs build from the tag, never from a commit passed between jobs:
the checks prove the tag's commit is on master, and each later job checks
out the tag again and fails if it now points anywhere else. A checkout of a
job output is code the workflow cannot show was reviewed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE_WORKFLOWS = (
    "dictate-npm-release.yml",
    "dictate-release-checks.yml",
    "dictate-release-prepare.yml",
    "dictate-release-promote.yml",
    "dictate-release-publish.yml",
)
# The workflows that change anything: they push a tag, publish, or move a channel.
CHANGING_WORKFLOWS = (
    "dictate-npm-release.yml",
    "dictate-release-prepare.yml",
    "dictate-release-promote.yml",
    "dictate-release-publish.yml",
)
TAG_CHECKOUT = "refs/tags/${{ inputs.tag }}"


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _load(name: str) -> dict:
    return yaml.safe_load(_text(name))


def _jobs(name: str) -> dict[str, dict]:
    return _load(name)["jobs"]


def _checkouts(job: dict) -> list[tuple[int, dict]]:
    return [
        (index, step)
        for index, step in enumerate(job.get("steps") or [])
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]


def _environment(job: dict) -> str | None:
    environment = job.get("environment")
    if isinstance(environment, dict):
        return environment.get("name")
    return environment


class ReleaseWorkflowFileTests(unittest.TestCase):
    def test_every_workflow_parses(self) -> None:
        for path in sorted(WORKFLOWS.glob("*.yml")):
            with self.subTest(workflow=path.name):
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIn("jobs", data)

    def test_the_release_workflows_are_named_like_flows(self) -> None:
        found = sorted(
            path.name
            for path in WORKFLOWS.glob("dictate-*.yml")
            if "release" in path.name
        )
        self.assertEqual(found, sorted(RELEASE_WORKFLOWS))

    def test_the_old_release_workflows_say_they_are_replaced(self) -> None:
        for name in ("release.yml", "npm-unstable.yml"):
            with self.subTest(workflow=name):
                first = _text(name).splitlines()[0]
                self.assertTrue(first.startswith("# Replaced by the dictate-* release workflows"), first)

    def test_no_release_workflow_names_flow_or_field(self) -> None:
        for name in RELEASE_WORKFLOWS:
            with self.subTest(workflow=name):
                text = _text(name)
                self.assertNotRegex(text, r"flow-|field-|arcforgelabs/flow|arcforgelabs/field|refs/heads/main\b")


class CheckoutRuleTests(unittest.TestCase):
    def test_no_release_job_checks_out_a_job_output(self) -> None:
        for name in RELEASE_WORKFLOWS:
            for job_id, job in _jobs(name).items():
                for _, step in _checkouts(job):
                    ref = str((step.get("with") or {}).get("ref", ""))
                    with self.subTest(workflow=name, job=job_id):
                        self.assertNotIn("needs.", ref)

    def test_every_job_that_builds_or_publishes_checks_out_the_tag(self) -> None:
        # The jobs that build release bytes or attach them to the release.
        building = {
            "dictate-release-checks.yml": {"resolve", "package", "linux-desktop", "windows-desktop"},
            "dictate-release-publish.yml": {"github-release"},
        }
        for name, job_ids in building.items():
            jobs = _jobs(name)
            for job_id in job_ids:
                with self.subTest(workflow=name, job=job_id):
                    checkouts = _checkouts(jobs[job_id])
                    self.assertTrue(checkouts, "the job checks out the code it builds")
                    for _, step in checkouts:
                        self.assertEqual(step["with"]["ref"], TAG_CHECKOUT)

    def test_a_tag_checkout_after_resolve_requires_the_proved_commit(self) -> None:
        for name in RELEASE_WORKFLOWS:
            for job_id, job in _jobs(name).items():
                steps = job.get("steps") or []
                for index, step in _checkouts(job):
                    if (step.get("with") or {}).get("ref") != TAG_CHECKOUT:
                        continue
                    if step.get("name") == "Check out the tag":
                        continue  # resolve's own checkout proves the commit
                    following = steps[index + 1]
                    with self.subTest(workflow=name, job=job_id):
                        self.assertRegex(
                            str(following.get("env", {}).get("RESOLVED", "")),
                            r"^\$\{\{ needs\.\w+\.outputs\.commit \}\}$",
                        )
                        self.assertIn('"$head" != "$RESOLVED"', following["run"])

    def test_the_only_other_checkouts_are_masters_tooling(self) -> None:
        others = []
        for name in RELEASE_WORKFLOWS:
            for job_id, job in _jobs(name).items():
                for _, step in _checkouts(job):
                    ref = (step.get("with") or {}).get("ref")
                    if ref != TAG_CHECKOUT:
                        others.append((name, job_id, ref))
        self.assertEqual(
            sorted(others, key=str),
            sorted(
                [
                    ("dictate-release-prepare.yml", "prepare", "master"),
                    ("dictate-release-promote.yml", "promote", None),
                ],
                key=str,
            ),
        )

    def test_the_checks_run_ci_on_the_proved_commit(self) -> None:
        ci = _jobs("dictate-release-checks.yml")["ci"]
        self.assertEqual(ci["uses"], "./.github/workflows/ci.yml")
        self.assertEqual(ci["with"]["ref"], "${{ needs.resolve.outputs.commit }}")
        ci_workflow = _load("ci.yml")
        triggers = ci_workflow[True]  # PyYAML reads the key `on` as True
        self.assertIn("workflow_call", triggers)
        for job_id, job in ci_workflow["jobs"].items():
            for _, step in _checkouts(job):
                with self.subTest(job=job_id):
                    self.assertEqual(step["with"]["ref"], "${{ inputs.ref }}")


class EnvironmentTests(unittest.TestCase):
    def test_changing_workflows_run_only_from_master(self) -> None:
        for name in CHANGING_WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertRegex(
                    _text(name),
                    r"- name: Require the workflow from master\n\s+if: github\.ref != 'refs/heads/master'",
                )

    def test_publish_approves_in_release_or_release_beta(self) -> None:
        approve = _jobs("dictate-release-publish.yml")["approve"]
        self.assertEqual(
            approve["environment"],
            "${{ needs.guard.outputs.channel == 'stable' && 'release' || 'release-beta' }}",
        )
        self.assertEqual(approve["permissions"], {})
        github_release = _jobs("dictate-release-publish.yml")["github-release"]
        self.assertIn("approve", github_release["needs"])
        self.assertIn("checks", github_release["needs"])

    def test_npm_publish_runs_in_npm_publish_with_oidc(self) -> None:
        jobs = _jobs("dictate-npm-release.yml")
        self.assertEqual(_environment(jobs["publish"]), "npm-publish")
        self.assertEqual(jobs["publish"]["permissions"]["id-token"], "write")
        self.assertEqual(_environment(jobs["approve"]), "npm-release")

    def test_promote_runs_in_npm_release_with_oidc(self) -> None:
        promote = _jobs("dictate-release-promote.yml")["promote"]
        self.assertEqual(_environment(promote), "npm-release")
        self.assertEqual(promote["permissions"]["id-token"], "write")

    def test_only_the_trusted_publisher_jobs_get_an_oidc_token(self) -> None:
        holders = []
        for name in RELEASE_WORKFLOWS:
            data = _load(name)
            self.assertNotEqual((data.get("permissions") or {}).get("id-token"), "write", name)
            for job_id, job in data["jobs"].items():
                if (job.get("permissions") or {}).get("id-token") == "write":
                    holders.append((name, job_id, _environment(job)))
        self.assertEqual(
            sorted(holders),
            [
                ("dictate-npm-release.yml", "publish", "npm-publish"),
                ("dictate-release-promote.yml", "promote", "npm-release"),
            ],
        )

    def test_no_release_workflow_uses_a_stored_npm_token(self) -> None:
        for name in RELEASE_WORKFLOWS:
            with self.subTest(workflow=name):
                text = _text(name)
                self.assertNotIn("NPM_TOKEN", text)
                self.assertNotIn("NODE_AUTH_TOKEN:", text)
                for job in _jobs(name).values():
                    for step in job.get("steps") or []:
                        # A registry-url makes npm use a token instead of OIDC.
                        self.assertNotIn("registry-url", step.get("with") or {})


class TrustedPublisherTests(unittest.TestCase):
    """npm's trusted publishers name these exact files and environments."""

    PUBLISHERS = (
        ("dictate-npm-release.yml", "npm-publish"),
        ("dictate-release-promote.yml", "npm-release"),
        ("npm-unstable.yml", "npm-publish"),
    )

    def test_the_docs_name_each_trusted_publisher(self) -> None:
        for doc in ("docs/RELEASING.md", "docs/release-versioning.md"):
            text = (ROOT / doc).read_text(encoding="utf-8")
            for workflow, environment in self.PUBLISHERS:
                with self.subTest(doc=doc, workflow=workflow):
                    self.assertRegex(
                        text,
                        rf"\| `{re.escape(workflow)}` \| `{re.escape(environment)}` \|",
                    )

    def test_each_workflow_names_itself_for_its_trusted_publisher(self) -> None:
        self.assertIn("names this file\n# (dictate-npm-release.yml) and environment npm-publish", _text("dictate-npm-release.yml"))
        self.assertIn("npm's trusted publisher for this file (environment npm-release)", _text("dictate-release-promote.yml"))
        unstable = _load("npm-unstable.yml")["jobs"]["publish"]
        self.assertEqual(_environment(unstable), "npm-publish")

    def test_dist_tags_are_always_explicit_and_npm_can_move_them(self) -> None:
        npm = _text("dictate-npm-release.yml")
        self.assertIn('npm publish "./${TARBALL}" --access public --tag "$DIST_TAG"', npm)
        self.assertIn("beta:beta|stable:latest|correction:latest) ;;", npm)
        promote = _text("dictate-release-promote.yml")
        self.assertIn('npm dist-tag add "${PACKAGE}@${VERSION}" beta', promote)
        self.assertIn('npm dist-tag add "${PACKAGE}@${VERSION}" latest', promote)
        self.assertIn("python scripts/calver.py newest", promote)
        for name in ("dictate-npm-release.yml", "dictate-release-promote.yml"):
            match = re.search(r'NPM_VERSION: "(\d+)\.(\d+)\.(\d+)"', _text(name))
            self.assertIsNotNone(match, name)
            self.assertGreaterEqual(tuple(int(part) for part in match.groups()), (11, 21, 0), name)


class PublishFlowTests(unittest.TestCase):
    def test_the_release_is_a_draft_until_npm_serves_the_version(self) -> None:
        publish = _text("dictate-release-publish.yml")
        self.assertIn("--verify-tag --draft", publish)
        self.assertIn("name: release-manifest\n", publish)
        self.assertIn("gh workflow run dictate-npm-release.yml", publish)
        npm = _text("dictate-npm-release.yml")
        self.assertIn("--draft=false", npm)
        # The draft is hidden from a read-only token, so the manifest travels
        # as an artifact of the Publish run.
        self.assertIn('gh run download "$RUN_ID" --repo "$GITHUB_REPOSITORY" --name release-manifest', npm)
        self.assertNotIn("gh release download", npm)
        jobs = _jobs("dictate-npm-release.yml")
        evidence = jobs["evidence"]
        self.assertIn("publish", evidence["needs"])

    @unittest.skipUnless(shutil.which("bash") and os.name != "nt", "needs bash")
    def test_a_rerun_for_an_older_stable_never_moves_githubs_latest_back(self) -> None:
        steps = _jobs("dictate-npm-release.yml")["evidence"]["steps"]
        script = next(step["run"] for step in steps if step.get("name") == "Make the GitHub Release public")
        cases = [
            ("v2026.10.4", "v2026.10.3", "--latest=false"),
            ("v2026.10.3", "v2026.10.4", "--latest"),
            ("v2026.10.9", "v2026.10.10", "--latest"),
            ("v2026.10.3-1", "v2026.10.3", "--latest=false"),
            ("", "v2026.10.3", "--latest"),
        ]
        for current, tag, expected in cases:
            with self.subTest(current=current, tag=tag), tempfile.TemporaryDirectory() as tmp:
                log = Path(tmp, "gh.log")
                fake = Path(tmp, "gh")
                fake.write_text(
                    "#!/usr/bin/env bash\n"
                    'if [[ "$1" == api ]]; then [[ -n "$CURRENT" ]] && echo "$CURRENT" && exit 0; exit 1; fi\n'
                    'echo "$*" >> "$LOG"\n'
                )
                fake.chmod(0o755)
                env = dict(os.environ, PATH=f"{tmp}:{os.environ['PATH']}", LOG=str(log), CURRENT=current,
                           TAG=tag, CHANNEL="stable", GITHUB_REPOSITORY="arcforgelabs/dictate",
                           GITHUB_SERVER_URL="https://github.com", GITHUB_STEP_SUMMARY=str(Path(tmp, "summary")))
                subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True)
                edit = log.read_text().split()
                self.assertIn(expected, edit)

    def test_every_asset_has_a_sha256_file_written_as_release_yml_writes_them(self) -> None:
        checks = _text("dictate-release-checks.yml")
        release = _text("release.yml")
        linux = 'sha256sum "$artifact" > "$artifact.sha256"'
        windows = "$hash  $(Split-Path $_ -Leaf)`n"
        self.assertIn(windows, release)
        self.assertIn("$hash  $($artifact.Name)`n", checks)
        self.assertIn(linux, checks)
        self.assertIn('sha256sum "$file" > "$file.sha256"', _text("dictate-release-publish.yml"))

    def test_the_manifest_records_every_file_and_the_npm_integrity(self) -> None:
        publish = _text("dictate-release-publish.yml")
        self.assertIn("release-manifest.json", publish)
        for field in ("files: $files[0]", "integrity: $integrity", "distTag: $distTag", "commit: $commit"):
            self.assertIn(field, publish)

    def test_the_windows_release_gate_starts_only_for_a_published_stable_release(self) -> None:
        gate = _jobs("dictate-npm-release.yml")["windows-gate"]
        self.assertIn("evidence", gate["needs"])
        self.assertIn("needs.resolve.outputs.channel != 'beta'", gate["if"])
        self.assertIn("gh workflow run windows-release-gate.yml", gate["steps"][0]["run"])

    def test_betas_and_corrections_are_stamped_only_in_the_build_jobs(self) -> None:
        jobs = _jobs("dictate-release-checks.yml")
        for job_id in ("package", "linux-desktop", "windows-desktop"):
            with self.subTest(job=job_id):
                runs = "\n".join(str(step.get("run", "")) for step in jobs[job_id]["steps"])
                self.assertRegex(runs, r"sync_release_version\.py \S*VERSION\S* --stamp")


class TagPatternTests(unittest.TestCase):
    TAGS = {
        "v2026.10.3": True,
        "v2026.10.32": True,
        "v2026.10.3-1": True,
        "v2026.10.3-beta.1": True,
        "v2026.10.3-beta.12": True,
        "v2026.10.3-unstable.71.1": False,
        "v2026.10.03": False,
        "v2026.13.1": False,
        "v2026.10.3-beta.0": False,
        "v2026.10.3-0": False,
        "2026.10.3": False,
    }

    def test_every_tag_pattern_accepts_betas_and_corrections(self) -> None:
        for name in ("dictate-npm-release.yml", "dictate-release-promote.yml"):
            patterns = re.findall(r'=~ (\^v20\S+\$) \]\]', _text(name))
            self.assertEqual(len(patterns), 1, name)
            pattern = re.compile(patterns[0])
            for tag, accepted in self.TAGS.items():
                with self.subTest(workflow=name, tag=tag):
                    self.assertEqual(bool(pattern.fullmatch(tag)), accepted)

    def test_publish_reads_the_channel_from_the_tag(self) -> None:
        patterns = re.findall(r'=~ (\^v20\S+\$) \]\]', _text("dictate-release-publish.yml"))
        beta, stable = (re.compile(pattern) for pattern in patterns)
        for tag, accepted in self.TAGS.items():
            with self.subTest(tag=tag):
                channel = "beta" if beta.fullmatch(tag) else "stable" if stable.fullmatch(tag) else None
                expected = None if not accepted else ("beta" if "-beta." in tag else "stable")
                self.assertEqual(channel, expected)


if __name__ == "__main__":
    unittest.main()
