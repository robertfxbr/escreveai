import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import json

from vision import analyze_with_gemini


class FakeInteractions:
    def __init__(self):
        self.created = []
        self.get_calls = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(id="job-123", status="in_progress")

    def get(self, job_id):
        self.get_calls.append(job_id)
        return SimpleNamespace(
            id=job_id, status="completed",
            output_text="[00:30] Aparece um gráfico.",
        )


class VisionTests(unittest.TestCase):
    def test_background_job_sends_video_and_returns_visual_notes(self):
        interactions = FakeInteractions()
        client = SimpleNamespace(interactions=interactions)
        with tempfile.TemporaryDirectory() as directory:
            result = analyze_with_gemini(
                "https://www.youtube.com/watch?v=aaaaaaaaaaa",
                Path(directory), lambda _: None, "test-key",
                client_factory=lambda **_: client,
                sleep=lambda _: None,
            )
            self.assertIn("gráfico", result)
            self.assertEqual(interactions.get_calls, ["job-123"])
            sent = interactions.created[0]
            self.assertTrue(sent["background"])
            self.assertEqual(sent["input"][0]["processing"], "agentic")
            self.assertEqual(sent["input"][0]["uri"], "https://www.youtube.com/watch?v=aaaaaaaaaaa")
            jobs = list(Path(directory).glob(".escreveai-vision-*.json"))
            self.assertEqual(len(jobs), 1)
            self.assertIn("gráfico", json.loads(jobs[0].read_text(encoding="utf-8"))["notes"])

    def test_resumes_pending_job_without_creating_another(self):
        interactions = FakeInteractions()
        client = SimpleNamespace(interactions=interactions)
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / ".escreveai-vision-aaaaaaaaaaa.json"
            job.write_text(
                '{"url":"https://www.youtube.com/watch?v=aaaaaaaaaaa",'
                '"model":"gemini-3.8-flash","id":"previous-job"}',
                encoding="utf-8",
            )
            analyze_with_gemini(
                "https://www.youtube.com/watch?v=aaaaaaaaaaa",
                Path(directory), lambda _: None, "test-key",
                client_factory=lambda **_: client,
                sleep=lambda _: None,
            )
            self.assertEqual(interactions.created, [])
            self.assertEqual(interactions.get_calls, ["previous-job"])
            self.assertTrue(job.exists())
            again = analyze_with_gemini(
                "https://www.youtube.com/watch?v=aaaaaaaaaaa",
                Path(directory), lambda _: None, "test-key",
                client_factory=lambda **_: client,
                sleep=lambda _: None,
            )
            self.assertIn("gráfico", again)
            self.assertEqual(interactions.get_calls, ["previous-job"])


if __name__ == "__main__":
    unittest.main()
