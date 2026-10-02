import queue
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import TranscriptionApp


class AppCancellationTests(unittest.TestCase):
    def test_cancel_button_requests_stop(self):
        status = SimpleNamespace(set=lambda value: updates.append(value))
        button = SimpleNamespace(configure=lambda **kwargs: states.append(kwargs["state"]))
        updates = []
        states = []
        app = TranscriptionApp.__new__(TranscriptionApp)
        app.cancel_event = threading.Event()
        app.status = status
        app.cancel_button = button

        app._cancel()

        self.assertTrue(app.cancel_event.is_set())
        self.assertEqual(states, ["disabled"])
        self.assertIn("Cancelando", updates[0])

    def test_worker_passes_cancel_event_to_pipeline(self):
        app = TranscriptionApp.__new__(TranscriptionApp)
        app.events = queue.Queue()
        app.cancel_event = threading.Event()
        result = SimpleNamespace(saved=[], failed=[], skipped=[], cancelled=True)

        with patch("app.transcribe_url", return_value=result) as transcribe:
            app._run(
                "https://www.youtube.com/watch?v=aaaaaaaaaaa", Path("."), "small",
                False, False, False, "", 3, "",
            )

        self.assertIs(transcribe.call_args.kwargs["cancel_event"], app.cancel_event)
        self.assertEqual(app.events.get_nowait(), ("done", result))


if __name__ == "__main__":
    unittest.main()
