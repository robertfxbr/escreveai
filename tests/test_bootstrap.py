import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bootstrap import ensure_dependencies


class BootstrapTests(unittest.TestCase):
    def test_installs_only_when_requirements_change(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".venv").mkdir()
            (project / "requirements.txt").write_text("package-one==1\n", encoding="utf-8")
            (project / "requirements-vision.txt").write_text("-r requirements.txt\n", encoding="utf-8")

            with patch("bootstrap.subprocess.run") as run:
                self.assertTrue(ensure_dependencies(project, Path("python.exe")))
                self.assertFalse(ensure_dependencies(project, Path("python.exe")))
                (project / "requirements.txt").write_text("package-one==2\n", encoding="utf-8")
                self.assertTrue(ensure_dependencies(project, Path("python.exe")))

            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][:4], ["python.exe", "-m", "pip", "install"])

    def test_failed_install_does_not_mark_dependencies_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".venv").mkdir()
            (project / "requirements.txt").write_text("package-one==1\n", encoding="utf-8")
            (project / "requirements-vision.txt").write_text("-r requirements.txt\n", encoding="utf-8")

            with patch("bootstrap.subprocess.run", side_effect=subprocess.CalledProcessError(1, "pip")):
                with self.assertRaises(subprocess.CalledProcessError):
                    ensure_dependencies(project, Path("python.exe"))

            self.assertFalse((project / ".venv" / "requirements.sha256").exists())


if __name__ == "__main__":
    unittest.main()
