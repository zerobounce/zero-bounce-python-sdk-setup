"""Repository posture: publish workflow, build pins, Dockerfile and sdist manifest.

Checks run on the source tree; from an unpacked sdist (which carries no .github or Dockerfile) they skip.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLISH = ROOT / ".github" / "workflows" / "publish.yml"


def _jobs(text):
    """Split the jobs: block of a workflow into {job id: text}."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([a-z][a-z-]*):\n", body)
    return dict(zip(parts[1::2], parts[2::2]))


@unittest.skipUnless(PUBLISH.exists(), "source tree only")
class PublishWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = PUBLISH.read_text()
        self.jobs = _jobs(self.text)

    def test_concurrency_group_without_cancel(self):
        self.assertRegex(self.text, r"(?m)^concurrency:\n  group: publish-\$\{\{ github.workflow \}\}\n  cancel-in-progress: false")

    def test_tag_requires_v_prefix(self):
        self.assertIn("re='^v[0-9]+", self.text)

    def test_environment_only_on_publish_job(self):
        with_env = [name for name, body in self.jobs.items() if re.search(r"(?m)^    environment: release$", body)]
        self.assertEqual(with_env, ["publish"])
        self.assertIn("id-token: write", self.jobs["publish"])

    def test_every_job_after_validation_checks_out_the_validated_sha(self):
        for name in ("test", "publish", "release"):
            self.assertIn("ref: ${{ needs.validate-tag.outputs.tag_sha }}", self.jobs[name], name)

    def test_only_publish_job_has_id_token(self):
        for name, body in self.jobs.items():
            if name == "publish":
                self.assertIn("id-token: write", body)
            else:
                self.assertNotIn("id-token", body, name)

    def test_build_is_without_isolation_with_hashed_tools(self):
        self.assertIn("python -m build --no-isolation", self.jobs["publish"])
        self.assertIn("--require-hashes -r requirements-build.txt", self.jobs["publish"])

    def test_every_checkout_drops_credentials(self):
        checkouts = re.findall(r"(?s)uses: actions/checkout@.*?(?=\n      - |\Z)", self.text)
        self.assertGreaterEqual(len(checkouts), 4)
        for block in checkouts:
            self.assertIn("persist-credentials: false", block)
            self.assertNotIn("persist-credentials: true", block)

    def test_actions_are_sha_pinned(self):
        for line in re.findall(r"(?m)^\s+uses: (\S+)", self.text):
            self.assertRegex(line, r"@[0-9a-f]{40}$")

    def test_build_tools_are_hashed(self):
        self.assertIn("--require-hashes -r requirements-build.txt", self.text)
        self.assertNotIn("--upgrade pip build", self.text)
        lock = (ROOT / "requirements-build.txt").read_text()
        self.assertRegex(lock, r"(?m)^setuptools==\d+\.\d+(\.\d+)? ")
        self.assertIn("--hash=sha256:", lock)


@unittest.skipUnless((ROOT / "Dockerfile").exists(), "source tree only")
class DockerfileTest(unittest.TestCase):
    def test_base_image_is_digest_pinned(self):
        self.assertRegex((ROOT / "Dockerfile").read_text(), r"(?m)^FROM python:3\.14-slim@sha256:[0-9a-f]{64}$")

    def test_dependabot_watches_docker(self):
        text = (ROOT / ".github" / "dependabot.yml").read_text()
        self.assertIn('package-ecosystem: "docker"', text)
        self.assertIn("version-update:semver-minor", text)


class PackagingTest(unittest.TestCase):
    def test_classifiers_cover_ci_pythons(self):
        text = (ROOT / "pyproject.toml").read_text()
        for v in ("3.10", "3.14", "3.15"):
            self.assertIn(f"Programming Language :: Python :: {v}", text)

    def test_build_backend_has_upper_bounds(self):
        requires = re.search(r"(?m)^requires = (\[.*\])$", (ROOT / "pyproject.toml").read_text()).group(1)
        for item in re.findall(r'"([^"]+)"', requires):
            self.assertIn("<", item, item)

    def test_manifest_ships_test_support(self):
        manifest = ROOT / "MANIFEST.in"
        if not manifest.exists():
            self.skipTest("sdist")
        text = manifest.read_text()
        for needed in ("tests/__init__.py", "tests/zero_bounce_test_case.py", "tests/fixtures/*.tsv"):
            self.assertIn(needed, text)
