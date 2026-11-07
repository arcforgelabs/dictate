"""The supported Linux source checks cannot publish or require a private runner."""
from pathlib import Path
import unittest

import yaml


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


class LinuxWorkflowPolicyTests(unittest.TestCase):
    def test_workflows_use_hosted_linux_runners(self) -> None:
        for path in WORKFLOWS.glob("*.yml"):
            workflow = yaml.safe_load(path.read_text())
            for name, job in workflow["jobs"].items():
                with self.subTest(workflow=path.name, job=name):
                    self.assertRegex(job["runs-on"], r"^ubuntu-[a-z0-9.]+$")

    def test_workflows_cannot_publish_packages_or_deploy(self) -> None:
        for path in WORKFLOWS.glob("*.yml"):
            workflow = yaml.safe_load(path.read_text())
            for name, job in workflow["jobs"].items():
                with self.subTest(workflow=path.name, job=name):
                    permissions = job.get("permissions", workflow.get("permissions", {}))
                    self.assertIsInstance(permissions, dict)
                    for permission in ("contents", "packages", "deployments", "id-token"):
                        self.assertNotEqual(permissions.get(permission), "write")
                    self.assertNotIn("environment", job)


if __name__ == "__main__":
    unittest.main()
