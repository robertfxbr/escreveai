import queue
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app import TranscriptionApp
from downloader import DownloadCancelled


class AppDownloadTests(unittest.TestCase):
    def test_download_worker_passes_selected_folder_cookies_and_cancel_event(self):
        app = TranscriptionApp.__new__(TranscriptionApp)
        app.events = queue.Queue()
        app.cancel_event = threading.Event()
        folder = Path("videos")
        saved = folder / "aula.mp4"

        with patch("app.download_video", return_value=saved) as download:
            app._run_download("https://example.com/video", folder, "cookies.txt")

        self.assertEqual(download.call_args.args[:2], ("https://example.com/video", folder))
        self.assertEqual(download.call_args.kwargs["cookie_file"], Path("cookies.txt"))
        self.assertIs(download.call_args.kwargs["cancel_event"], app.cancel_event)
        self.assertEqual(app.events.get_nowait(), ("download_done", saved))

    def test_download_worker_reports_cancellation_without_an_error(self):
        app = TranscriptionApp.__new__(TranscriptionApp)
        app.events = queue.Queue()
        app.cancel_event = threading.Event()
        with patch("app.download_video", side_effect=DownloadCancelled()):
            app._run_download("https://example.com/video", Path("videos"), "")
        self.assertEqual(app.events.get_nowait(), ("download_cancelled", None))


if __name__ == "__main__":
    unittest.main()
