import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from downloader import DownloadCancelled, download_video, validate_media_url


class DownloaderTests(unittest.TestCase):
    def test_accepts_web_urls_and_rejects_local_file_schemes(self):
        url = "https://example.com/video?id=1"
        self.assertEqual(validate_media_url(url), url)
        for invalid in ("", "file:///private/video.mp4", "javascript:alert(1)",
                        "ftp://example.com/video", "https://user:pass@example.com/video"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_media_url(invalid)

    def test_download_saves_one_video_with_cookie_and_reports_result(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            cookie_file = folder / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            destination = folder / "Aula [Example-123].mp4"
            calls = []

            class FakeYoutubeDL:
                def __init__(self, options):
                    self.options = options
                    calls.append(options)

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def extract_info(self, url, download):
                    if not download:
                        return {"id": "123", "title": "Aula"}
                    destination.write_bytes(b"video")
                    self.options["progress_hooks"][0](
                        {"status": "downloading", "downloaded_bytes": 5, "total_bytes": 5}
                    )
                    return {"id": "123", "title": "Aula", "filepath": str(destination)}

            messages = []
            with patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
                saved = download_video(
                    "https://example.com/video", folder, messages.append, cookie_file=cookie_file
                )

            self.assertEqual(saved, destination)
            self.assertEqual(saved.read_bytes(), b"video")
            self.assertEqual(calls[0]["cookiefile"], str(cookie_file))
            self.assertTrue(calls[0]["noplaylist"])
            self.assertTrue(calls[0]["nooverwrites"])
            self.assertIn("Baixando", " ".join(messages))

    def test_playlist_is_rejected_before_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            class FakeYoutubeDL:
                def __init__(self, options):
                    self.options = options

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def extract_info(self, url, download):
                    if download:
                        self.fail("should not download")
                    return {"_type": "playlist", "entries": [{"id": "1"}]}

            with patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
                with self.assertRaisesRegex(ValueError, "playlist"):
                    download_video("https://example.com/playlist", Path(directory))

    def test_cancel_stops_download_and_keeps_partial_file_for_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            event = threading.Event()
            partial = folder / "video.mp4.part"

            class FakeYoutubeDL:
                def __init__(self, options):
                    self.options = options

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def extract_info(self, url, download):
                    if not download:
                        return {"id": "123"}
                    partial.write_bytes(b"partial")
                    event.set()
                    self.options["progress_hooks"][0]({"status": "downloading"})

            with patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
                with self.assertRaises(DownloadCancelled):
                    download_video("https://example.com/video", folder, cancel_event=event)
            self.assertEqual(partial.read_bytes(), b"partial")


if __name__ == "__main__":
    unittest.main()
