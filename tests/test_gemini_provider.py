"""
GeminiProvider unit tests — focused on _to_gemini_contents multimodal fix.

Guards the bug fix where image_url parts were silently dropped.
No live network calls — GEMINI_API_KEY is never read from a real environment.
"""
from __future__ import annotations

import base64
import os

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-do-not-use-in-prod")

import pytest
from app.ai.models import Message, TextPart, ImagePart
from app.ai.providers.gemini import _to_gemini_contents, _image_part


class TestToGeminiContents:
    def test_plain_string_message(self):
        result = _to_gemini_contents([Message(role="user", content="hello")])
        assert result == [{"role": "user", "parts": [{"text": "hello"}]}]

    def test_assistant_role_mapped_to_model(self):
        result = _to_gemini_contents([Message(role="assistant", content="ok")])
        assert result[0]["role"] == "model"

    def test_system_messages_skipped(self):
        msgs = [
            Message(role="system", content="be helpful"),
            Message(role="user", content="hi"),
        ]
        result = _to_gemini_contents(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_text_only_multipart(self):
        msgs = [Message(role="user", content=[TextPart(text="describe this")])]
        result = _to_gemini_contents(msgs)
        assert result[0]["parts"] == [{"text": "describe this"}]

    def test_image_url_https_not_silently_dropped(self):
        """Core regression: image_url parts must appear in parts, not be dropped."""
        msgs = [Message(role="user", content=[
            TextPart(text="what is this?"),
            ImagePart(url="https://example.com/cat.jpg"),
        ])]
        result = _to_gemini_contents(msgs)
        parts = result[0]["parts"]
        assert len(parts) == 2
        assert parts[0] == {"text": "what is this?"}
        assert "file_data" in parts[1]
        assert parts[1]["file_data"]["file_uri"] == "https://example.com/cat.jpg"

    def test_image_only_message_has_parts(self):
        msgs = [Message(role="user", content=[
            ImagePart(url="https://example.com/img.png"),
        ])]
        result = _to_gemini_contents(msgs)
        assert len(result[0]["parts"]) == 1
        assert "file_data" in result[0]["parts"][0]

    def test_data_uri_becomes_inline_data(self):
        raw = b"fake-image-bytes"
        b64 = base64.b64encode(raw).decode()
        url = f"data:image/jpeg;base64,{b64}"
        msgs = [Message(role="user", content=[ImagePart(url=url)])]
        result = _to_gemini_contents(msgs)
        part = result[0]["parts"][0]
        assert "inline_data" in part
        assert part["inline_data"]["mime_type"] == "image/jpeg"
        assert part["inline_data"]["data"] == b64

    def test_data_uri_png_mime_type(self):
        b64 = base64.b64encode(b"png-data").decode()
        url = f"data:image/png;base64,{b64}"
        msgs = [Message(role="user", content=[ImagePart(url=url)])]
        result = _to_gemini_contents(msgs)
        assert result[0]["parts"][0]["inline_data"]["mime_type"] == "image/png"

    def test_gs_uri_becomes_file_data(self):
        url = "gs://my-bucket/image.jpg"
        msgs = [Message(role="user", content=[ImagePart(url=url)])]
        result = _to_gemini_contents(msgs)
        assert result[0]["parts"][0] == {"file_data": {"file_uri": url}}

    def test_multiple_images_in_one_message(self):
        msgs = [Message(role="user", content=[
            TextPart(text="compare these"),
            ImagePart(url="https://example.com/a.jpg"),
            ImagePart(url="https://example.com/b.jpg"),
        ])]
        result = _to_gemini_contents(msgs)
        parts = result[0]["parts"]
        assert len(parts) == 3
        assert parts[0] == {"text": "compare these"}
        assert "file_data" in parts[1]
        assert "file_data" in parts[2]

    def test_empty_parts_list_gets_empty_text(self):
        """A message with no renderable parts must still produce a valid Gemini part."""
        msgs = [Message(role="user", content=[])]
        result = _to_gemini_contents(msgs)
        assert result[0]["parts"] == [{"text": ""}]

    def test_malformed_base64_skipped_not_crash(self):
        url = "data:image/jpeg;base64,!!!not-valid-base64!!!"
        part = _image_part(url)
        assert part == {}  # malformed → skipped silently


class TestImagePart:
    def test_https_url(self):
        result = _image_part("https://cdn.example.com/photo.jpg")
        assert result == {"file_data": {"file_uri": "https://cdn.example.com/photo.jpg"}}

    def test_http_url(self):
        result = _image_part("http://example.com/image.png")
        assert result == {"file_data": {"file_uri": "http://example.com/image.png"}}

    def test_gs_url(self):
        result = _image_part("gs://bucket/file.jpg")
        assert result == {"file_data": {"file_uri": "gs://bucket/file.jpg"}}

    def test_unknown_scheme_returns_empty(self):
        result = _image_part("ftp://example.com/image.jpg")
        assert result == {}

    def test_data_uri_valid(self):
        b64 = base64.b64encode(b"img").decode()
        result = _image_part(f"data:image/webp;base64,{b64}")
        assert result["inline_data"]["mime_type"] == "image/webp"

    def test_data_uri_malformed_base64_empty(self):
        result = _image_part("data:image/jpeg;base64,ZZZZ!!!")
        assert result == {}
