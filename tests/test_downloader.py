import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from downloader import DownloadCancelled, convert_hevc_to_h264, download_video, validate_media_url


def fake_ffprobe(codec, duration="10.0"):
    def run(command, **_):
        output = codec if "stream=codec_name" in command else duration
        return SimpleNamespace(stdout=f"{output}\n", returncode=0)
    return run


class FakeFfmpeg:
    """Writes the converted file and reports progress like ffmpeg -progress pipe:1."""

    instances = []

    def __init__(self, command, on_line=None, returncode=0, **_):
        self.command = command
        self.on_line = on_line
        self.returncode_value = returncode
        self.returncode = None
        Path(command[-1]).write_bytes(b"h264")
        self.stdout = self._lines()
        FakeFfmpeg.instances.append(self)

    def _lines(self):
        for line in ("out_time_us=5000000\n", "out_time_us=10000000\n", "progress=end\n"):
            if self.on_line:
                self.on_line()
            yield line

    def wait(self):
        if self.returncode is None:
            self.returncode = self.returncode_value
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


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


class HevcConversionTests(unittest.TestCase):
    def setUp(self):
        FakeFfmpeg.instances.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.video = Path(self.directory.name) / "Aula [TikTok-1].mp4"
        self.video.write_bytes(b"hevc")
        self.which = patch("downloader.shutil.which", side_effect=lambda name: name)
        self.which.start()

    def tearDown(self):
        self.which.stop()
        self.directory.cleanup()

    def test_hevc_is_converted_in_place_to_h264(self):
        messages = []
        with (
            patch("downloader.subprocess.run", fake_ffprobe("hevc")),
            patch("downloader.subprocess.Popen", FakeFfmpeg),
        ):
            converted = convert_hevc_to_h264(self.video, messages.append)

        self.assertTrue(converted)
        self.assertEqual(self.video.read_bytes(), b"h264")
        self.assertIn("libx264", FakeFfmpeg.instances[0].command)
        self.assertIn("Convertendo para H.264... 100%", messages)
        self.assertEqual(sorted(p.name for p in self.video.parent.iterdir()), [self.video.name])

    def test_other_codecs_are_left_untouched(self):
        with (
            patch("downloader.subprocess.run", fake_ffprobe("h264")),
            patch("downloader.subprocess.Popen", FakeFfmpeg),
        ):
            self.assertFalse(convert_hevc_to_h264(self.video))
        self.assertEqual(FakeFfmpeg.instances, [])
        self.assertEqual(self.video.read_bytes(), b"hevc")

    def test_missing_ffmpeg_keeps_original_and_warns(self):
        messages = []
        with patch("downloader.shutil.which", return_value=None):
            self.assertFalse(convert_hevc_to_h264(self.video, messages.append))
        self.assertIn("FFmpeg não encontrado", messages[0])
        self.assertEqual(self.video.read_bytes(), b"hevc")

    def test_failed_conversion_keeps_original(self):
        messages = []
        failing = lambda command, **kwargs: FakeFfmpeg(command, returncode=1, **kwargs)
        with (
            patch("downloader.subprocess.run", fake_ffprobe("hevc")),
            patch("downloader.subprocess.Popen", failing),
        ):
            self.assertFalse(convert_hevc_to_h264(self.video, messages.append))
        self.assertEqual(self.video.read_bytes(), b"hevc")
        self.assertIn("mantido em HEVC", messages[-1])
        self.assertEqual(sorted(p.name for p in self.video.parent.iterdir()), [self.video.name])

    def test_cancel_during_conversion_keeps_original_for_retry(self):
        event = threading.Event()
        cancelling = lambda command, **kwargs: FakeFfmpeg(command, on_line=event.set, **kwargs)
        with (
            patch("downloader.subprocess.run", fake_ffprobe("hevc")),
            patch("downloader.subprocess.Popen", cancelling),
        ):
            with self.assertRaises(DownloadCancelled):
                convert_hevc_to_h264(self.video, cancel_event=event)
        self.assertEqual(self.video.read_bytes(), b"hevc")
        self.assertEqual(sorted(p.name for p in self.video.parent.iterdir()), [self.video.name])


if __name__ == "__main__":
    unittest.main()
