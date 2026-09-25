import tempfile
import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from transcriber import (
    PlaylistVideo,
    VideoInfo,
    download_audio,
    format_timestamp,
    is_playlist_url,
    render_markdown,
    transcribe_url,
    transcribe_video,
    validate_youtube_url,
)


class TranscriberTests(unittest.TestCase):
    def test_audio_download_uses_cookies_and_retries_alternate_client(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            cookies = folder / "cookies.txt"
            cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            attempts = []

            class FakeYoutubeDL:
                def __init__(self, options):
                    self.options = options

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    return False

                def extract_info(self, url, download):
                    attempts.append(self.options)
                    if len(attempts) == 1:
                        raise RuntimeError("Login exigido")
                    Path(self.options["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(b"audio")
                    return {"id": "aaaaaaaaaaa", "title": "Aula", "duration": 10}

            with patch.dict(os.environ, {"YOUTUBE_COOKIES_FILE": str(cookies)}), \
                    patch("yt_dlp.YoutubeDL", FakeYoutubeDL):
                info, audio = download_audio(
                    "https://www.youtube.com/watch?v=aaaaaaaaaaa", folder, lambda _: None
                )
            self.assertEqual(info.video_id, "aaaaaaaaaaa")
            self.assertEqual(audio.read_bytes(), b"audio")
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0]["cookiefile"], str(cookies))
            self.assertEqual(attempts[1]["extractor_args"]["youtube"]["player_client"], ["android"])

    def test_accepts_video_links_but_rejects_playlists_and_other_hosts(self):
        for url in (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ?t=10",
            "https://m.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube.com/playlist?list=PLabc123",
        ):
            self.assertEqual(validate_youtube_url(url), url)
        for url in (
            "https://youtube.com/playlist",
            "https://youtube.com.evil.test/watch?v=abc",
            "https://youtube.com/watch?v=abc%2F..%2F..%2Fevil",
            "https://youtu.be/abc%2F..%2F..%2Fevil",
            "file:///secret",
            "not a url",
        ):
            with self.assertRaises(ValueError):
                validate_youtube_url(url)
        self.assertTrue(is_playlist_url("https://youtube.com/playlist?list=PLabc123"))
        self.assertTrue(is_playlist_url("https://youtube.com/watch?v=abc123&list=PLabc123"))
        self.assertFalse(is_playlist_url("https://youtube.com/watch?v=abc123"))

    def test_markdown_contains_all_segments_and_clickable_timestamps(self):
        info = VideoInfo("Aula de Python", "https://youtu.be/abc123", "abc123", 65)
        segments = [
            SimpleNamespace(start=0.0, text=" Olá, pessoal. "),
            SimpleNamespace(start=61.2, text="  Vamos começar.  "),
        ]
        content = render_markdown(info, segments)
        self.assertIn("# Aula de Python", content)
        self.assertIn("**Fonte:** https://youtu.be/abc123", content)
        self.assertIn("[00:00:00](https://www.youtube.com/watch?v=abc123&t=0s) Olá, pessoal.", content)
        self.assertIn("[00:01:01](https://www.youtube.com/watch?v=abc123&t=61s) Vamos começar.", content)
        self.assertEqual(format_timestamp(3661), "01:01:01")

    def test_optional_filler_cleanup_preserves_words_by_default(self):
        info = VideoInfo("Teste", "https://youtu.be/abc123", "abc123", None)
        segments = [SimpleNamespace(start=0, text="Ahn, hoje vamos começar.")]
        self.assertIn("Ahn, hoje", render_markdown(info, segments))
        self.assertIn("[00:00:00]", render_markdown(info, segments, remove_fillers=True))
        self.assertIn("hoje vamos começar.", render_markdown(info, segments, remove_fillers=True))
        self.assertNotIn("Ahn,", render_markdown(info, segments, remove_fillers=True))

    def test_pipeline_saves_complete_markdown_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []

            def download(url, temp_dir, status):
                calls.append("download")
                audio = temp_dir / "audio.webm"
                audio.write_bytes(b"test")
                return VideoInfo("Vídeo: teste?", url, "abc123", 12), audio

            def transcribe(audio, model_name, status):
                calls.append("transcribe")
                self.assertEqual(audio.read_bytes(), b"test")
                return [
                    SimpleNamespace(start=0, text="Primeiro trecho."),
                    SimpleNamespace(start=8, text="Último trecho."),
                ]

            first = transcribe_video(
                "https://youtu.be/abc123", Path(directory), "tiny", lambda _: None,
                downloader=download, transcriber=transcribe,
                caption_fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError("sem legendas")),
            )
            second = transcribe_video(
                "https://youtu.be/abc123", Path(directory), "tiny", lambda _: None,
                downloader=download, transcriber=transcribe,
                caption_fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError("sem legendas")),
            )
            self.assertNotEqual(first, second)
            self.assertEqual(calls, ["download", "transcribe"] * 2)
            self.assertIn("Último trecho.", first.read_text(encoding="utf-8"))
            self.assertIn("Último trecho.", second.read_text(encoding="utf-8"))
            self.assertEqual(len(list(Path(directory).iterdir())), 2)

    def test_pipeline_does_not_save_partial_file_on_error(self):
        with tempfile.TemporaryDirectory() as directory:
            def download(url, temp_dir, status):
                audio = temp_dir / "audio.webm"
                audio.write_bytes(b"test")
                return VideoInfo("Título", url, "abc123", None), audio

            def transcribe(audio, model_name, status):
                raise RuntimeError("Falha no modelo")

            with self.assertRaisesRegex(RuntimeError, "Falha no modelo"):
                transcribe_video(
                    "https://youtu.be/abc123", Path(directory), "tiny", lambda _: None,
                    downloader=download, transcriber=transcribe,
                    caption_fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError("sem legendas")),
                )
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_uses_captions_without_downloading_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            def captions(url, status):
                return VideoInfo("Vídeo abc123", url, "abc123", 14), [
                    SimpleNamespace(start=0, text="Olá pessoal", duration=3),
                    SimpleNamespace(start=3, text="Olá pessoal", duration=3),
                    SimpleNamespace(start=7, text="Hoje veremos Python", duration=4),
                ]

            def unexpected(*args):
                self.fail("Não deve baixar áudio quando as legendas estão disponíveis")

            saved = transcribe_video(
                "https://youtu.be/abc123", Path(directory), "tiny", lambda _: None,
                caption_fetcher=captions, downloader=unexpected, transcriber=unexpected,
            )
            content = saved.read_text(encoding="utf-8")
            self.assertEqual(content.count("Olá pessoal"), 1)
            self.assertIn("Hoje veremos Python", content)

    def test_can_force_whisper_even_with_captions(self):
        with tempfile.TemporaryDirectory() as directory:
            def download(url, temp_dir, status):
                audio = temp_dir / "audio.webm"
                audio.write_bytes(b"test")
                return VideoInfo("Vídeo", url, "abc123", 10), audio

            saved = transcribe_video(
                "https://youtu.be/abc123", Path(directory), "tiny", lambda _: None,
                force_whisper=True,
                caption_fetcher=lambda *_: self.fail("Não deve buscar legendas"),
                downloader=download,
                transcriber=lambda *_: [SimpleNamespace(start=0, text="Fala completa")],
            )
            self.assertIn("Fala completa", saved.read_text(encoding="utf-8"))

    def test_playlist_saves_one_file_per_video_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            urls = [
                "https://www.youtube.com/watch?v=aaaaaaaaaaa",
                "https://www.youtube.com/watch?v=bbbbbbbbbbb",
                "https://www.youtube.com/watch?v=ccccccccccc",
            ]
            statuses = []

            def captions(url, status):
                if "bbbbbbbbbbb" in url:
                    raise RuntimeError("Sem legendas")
                video_id = url.split("v=")[1]
                return VideoInfo(f"Vídeo {video_id}", url, video_id, None), [
                    SimpleNamespace(start=0, text=f"Fala {video_id}")
                ]

            result = transcribe_url(
                "https://www.youtube.com/playlist?list=PLabc123",
                Path(directory), "tiny", statuses.append,
                playlist_fetcher=lambda *_: urls,
                caption_fetcher=captions,
                downloader=lambda *_: (_ for _ in ()).throw(RuntimeError("Áudio indisponível")),
            )
            self.assertEqual(len(result.saved), 2)
            self.assertEqual(len(result.failed), 1)
            self.assertIn("bbbbbbbbbbb", result.failed[0][0])
            self.assertEqual(len(list(Path(directory).glob("*.md"))), 2)
            self.assertIn("3/3", " ".join(statuses))

    def test_playlist_uses_video_titles_in_filenames(self):
        with tempfile.TemporaryDirectory() as directory:
            video_url = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
            result = transcribe_url(
                "https://www.youtube.com/playlist?list=PLabc123",
                Path(directory), "tiny", lambda _: None,
                playlist_fetcher=lambda *_: [PlaylistVideo(video_url, "Aula 01: Introdução")],
                caption_fetcher=lambda url, status: (
                    VideoInfo("Vídeo aaaaaaaaaaa", url, "aaaaaaaaaaa", None),
                    [SimpleNamespace(start=0, text="Olá")],
                ),
            )
            self.assertIn("Aula 01 Introdução", result.saved[0].name)
            self.assertIn("# Aula 01: Introdução", result.saved[0].read_text(encoding="utf-8"))

    def test_rerun_recognizes_transcript_kept_under_legacy_note_name(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            url = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
            legacy = folder / "lecture_1.md"
            legacy.write_text(
                f"# Aula 1\n\n**Fonte:** {url}\n\n## Transcrição\n\n"
                "[00:00:00](https://www.youtube.com/watch?v=aaaaaaaaaaa&t=0s) Fala completa.\n",
                encoding="utf-8",
            )
            result = transcribe_url(
                url, folder, status=lambda _: None, visual_mode=True,
                api_key="fake-test-key",
                caption_fetcher=lambda *_: self.fail("Não deve buscar legendas de novo"),
                visual_analyzer=lambda *_: "[00:30] Gráfico na tela.",
            )
            self.assertEqual(result.saved, [legacy])
            self.assertEqual(len(list(folder.glob("*.md"))), 1)
            self.assertIn("## Contexto visual", legacy.read_text(encoding="utf-8"))

    def test_plain_rerun_skips_existing_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            url = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
            existing = folder / "lecture_1.md"
            existing.write_text(
                f"# Aula 1\n\n**Fonte:** {url}\n\n## Transcrição\n\nFala completa.\n",
                encoding="utf-8",
            )
            result = transcribe_url(
                url, folder, status=lambda _: None,
                caption_fetcher=lambda *_: self.fail("Não deve buscar legendas de novo"),
            )
            self.assertEqual(result.saved, [existing])
            self.assertEqual(result.skipped, [existing])
            self.assertEqual(len(list(folder.glob("*.md"))), 1)

    def test_visual_mode_adds_context_and_skips_completed_video_on_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            video_url = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
            calls = []

            def captions(url, status):
                calls.append("captions")
                return VideoInfo("Aula", url, "aaaaaaaaaaa", 120), [
                    SimpleNamespace(start=0, text="Veja o gráfico.")
                ]

            def vision(url, folder, status, api_key):
                calls.append("vision")
                return "[00:30] Gráfico mostra crescimento de 10 para 20."

            kwargs = dict(
                caption_fetcher=captions,
                visual_analyzer=vision,
                visual_mode=True,
                api_key="fake-test-key",
            )
            first = transcribe_url(video_url, Path(directory), status=lambda _: None, **kwargs)
            second = transcribe_url(video_url, Path(directory), status=lambda _: None, **kwargs)
            self.assertEqual(first.saved, second.saved)
            self.assertEqual(calls, ["captions", "vision"])
            content = first.saved[0].read_text(encoding="utf-8")
            self.assertIn("Veja o gráfico.", content)
            self.assertIn("## Contexto visual", content)
            self.assertIn("[00:00:30](https://www.youtube.com/watch?v=aaaaaaaaaaa&t=30s)", content)
            self.assertEqual(len(list(Path(directory).glob("*.md"))), 1)

    def test_visual_error_keeps_transcript_and_rerun_enriches_it(self):
        with tempfile.TemporaryDirectory() as directory:
            video_url = "https://www.youtube.com/watch?v=aaaaaaaaaaa"
            calls = []

            def captions(url, status):
                calls.append("captions")
                return VideoInfo("Aula", url, "aaaaaaaaaaa", 120), [
                    SimpleNamespace(start=0, text="Transcrição preservada.")
                ]

            failed = transcribe_url(
                video_url, Path(directory), status=lambda _: None,
                caption_fetcher=captions, visual_mode=True, api_key="fake-test-key",
                visual_analyzer=lambda *_: (_ for _ in ()).throw(RuntimeError("API indisponível")),
            )
            self.assertEqual(len(failed.failed), 1)
            files = list(Path(directory).glob("*.md"))
            self.assertEqual(len(files), 1)
            self.assertIn("Transcrição preservada.", files[0].read_text(encoding="utf-8"))

            resumed = transcribe_url(
                video_url, Path(directory), status=lambda _: None,
                caption_fetcher=captions, visual_mode=True, api_key="fake-test-key",
                visual_analyzer=lambda *_: "[00:30] Um gráfico.",
            )
            self.assertEqual(resumed.saved, files)
            self.assertEqual(calls, ["captions"])

    def test_visual_playlist_limit_resumes_next_video_on_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            ids = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
            urls = [f"https://www.youtube.com/watch?v={video_id}" for video_id in ids]
            analyzed = []

            def captions(url, status):
                video_id = url.split("v=")[1]
                return VideoInfo("Aula", url, video_id, 120), [
                    SimpleNamespace(start=0, text="Texto")
                ]

            def vision(url, folder, status, api_key):
                analyzed.append(url)
                return "[00:30] Slide na tela."

            kwargs = dict(
                playlist_fetcher=lambda *_: urls,
                caption_fetcher=captions,
                visual_analyzer=vision,
                visual_mode=True,
                api_key="fake-test-key",
                max_new_videos=1,
            )
            first = transcribe_url("https://youtube.com/playlist?list=PLabc", Path(directory), **kwargs)
            second = transcribe_url("https://youtube.com/playlist?list=PLabc", Path(directory), **kwargs)
            self.assertEqual(len(first.saved), 1)
            self.assertEqual(len(second.saved), 2)
            self.assertEqual(len(second.skipped), 1)
            self.assertEqual(analyzed, urls[:2])


if __name__ == "__main__":
    unittest.main()
