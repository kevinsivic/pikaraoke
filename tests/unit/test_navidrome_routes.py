"""Tests for Navidrome routes."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests as req
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

import pikaraoke.routes.navidrome as navidrome_module
from pikaraoke.routes.navidrome import navidrome_bp

SAMPLE_ENTRIES = [
    {"id": "song-1", "title": "Song One", "artist": "Artist A"},
    {"id": "song-2", "title": "Song Two", "artist": "Artist B"},
    {"id": "song-3", "title": "Song Three", "artist": "Artist C"},
]


def make_karaoke_mock(playlist_id="playlist-1"):
    mock = MagicMock()
    mock.navidrome_url = "http://navidrome:4533"
    mock.navidrome_username = "user"
    mock.navidrome_password = "pass"
    mock.navidrome_playlist_id = playlist_id
    return mock


def make_playlist_api_response(entries):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"subsonic-response": {"playlist": {"entry": entries}}}
    return mock_resp


SAMPLE_HLS_MANIFEST_ABSOLUTE = """\
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXTINF:10.0,
http://navidrome:4533/rest/stream.view?id=song-1&index=0
#EXTINF:8.5,
http://navidrome:4533/rest/stream.view?id=song-1&index=1
#EXT-X-ENDLIST"""

SAMPLE_HLS_MANIFEST_RELATIVE = """\
#EXTM3U
#EXT-X-TARGETDURATION:10
#EXTINF:10.0,
/rest/stream.view?id=song-1&index=0
#EXTINF:8.5,
/rest/stream.view?id=song-1&index=1
#EXT-X-ENDLIST"""


@pytest.fixture(autouse=True)
def reset_caches():
    navidrome_module._playlist_cache["entries"] = []
    navidrome_module._playlist_cache["fetched_at"] = 0.0
    navidrome_module._playlist_cache["playlist_id"] = None
    if hasattr(navidrome_module, "_segment_urls"):
        navidrome_module._segment_urls.clear()
    yield
    navidrome_module._playlist_cache["entries"] = []
    navidrome_module._playlist_cache["fetched_at"] = 0.0
    navidrome_module._playlist_cache["playlist_id"] = None
    if hasattr(navidrome_module, "_segment_urls"):
        navidrome_module._segment_urls.clear()


@pytest.fixture
def app():
    test_app = Flask(__name__)
    test_app.register_blueprint(navidrome_bp)
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


class TestNavidromeNext:
    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_returns_song_id_and_title_from_playlist(
        self, mock_requests, mock_get_instance, client
    ):
        """GET /navidrome_next returns a song id and title drawn from the configured playlist."""
        mock_get_instance.return_value = make_karaoke_mock()
        mock_requests.return_value = make_playlist_api_response(SAMPLE_ENTRIES)

        response = client.get("/navidrome_next")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["id"] in {"song-1", "song-2", "song-3"}
        assert data["title"] in {"Song One", "Song Two", "Song Three"}

    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_uses_cached_playlist_on_second_call(self, mock_requests, mock_get_instance, client):
        """Second call to /navidrome_next does not re-fetch the playlist from Navidrome."""
        mock_get_instance.return_value = make_karaoke_mock()
        mock_requests.return_value = make_playlist_api_response(SAMPLE_ENTRIES)

        client.get("/navidrome_next")
        client.get("/navidrome_next")

        assert mock_requests.call_count == 1

    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    @patch("pikaraoke.routes.navidrome.time")
    def test_refreshes_cache_after_ttl_expires(
        self, mock_time, mock_requests, mock_get_instance, client
    ):
        """Playlist is re-fetched from Navidrome once the cache TTL has elapsed."""
        mock_get_instance.return_value = make_karaoke_mock()
        mock_requests.return_value = make_playlist_api_response(SAMPLE_ENTRIES)

        mock_time.time.return_value = 0
        client.get("/navidrome_next")

        mock_time.time.return_value = 3601
        client.get("/navidrome_next")

        assert mock_requests.call_count == 2

    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_refreshes_cache_when_playlist_id_changes(
        self, mock_requests, mock_get_instance, client
    ):
        """Playlist is re-fetched when the configured playlist ID changes between calls."""
        mock_requests.return_value = make_playlist_api_response(SAMPLE_ENTRIES)

        mock_get_instance.return_value = make_karaoke_mock(playlist_id="playlist-1")
        client.get("/navidrome_next")

        mock_get_instance.return_value = make_karaoke_mock(playlist_id="playlist-2")
        client.get("/navidrome_next")

        assert mock_requests.call_count == 2

    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    def test_returns_empty_when_no_playlist_configured(self, mock_get_instance, client):
        """GET /navidrome_next returns an empty object when no playlist ID is configured."""
        mock_get_instance.return_value = make_karaoke_mock(playlist_id=None)

        response = client.get("/navidrome_next")

        assert response.status_code == 200
        assert json.loads(response.data) == {}

    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_returns_502_on_navidrome_connection_error(
        self, mock_requests, mock_get_instance, client
    ):
        """GET /navidrome_next returns 502 when Navidrome is unreachable."""
        mock_get_instance.return_value = make_karaoke_mock()
        mock_requests.side_effect = req.RequestException("connection refused")

        response = client.get("/navidrome_next")

        assert response.status_code == 502

    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_handles_single_entry_playlist(self, mock_requests, mock_get_instance, client):
        """Subsonic returns a dict (not list) for a single-entry playlist — handled correctly."""
        mock_get_instance.return_value = make_karaoke_mock()
        mock_requests.return_value = make_playlist_api_response(
            {"id": "song-1", "title": "Only Song", "artist": "Solo Artist"}
        )

        response = client.get("/navidrome_next")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["id"] == "song-1"


class TestManifestRewriting:
    def test_preserves_hls_tags_unchanged(self):
        """HLS tag/comment lines (starting with #) pass through the rewriter unchanged."""
        from pikaraoke.routes.navidrome import _rewrite_manifest

        manifest, _ = _rewrite_manifest(
            SAMPLE_HLS_MANIFEST_ABSOLUTE, "http://navidrome:4533", "song-1"
        )
        lines = manifest.splitlines()

        assert lines[0] == "#EXTM3U"
        assert lines[1] == "#EXT-X-VERSION:3"
        assert "#EXT-X-ENDLIST" in lines

    def test_rewrites_absolute_segment_urls_to_proxy_paths(self):
        """Absolute segment URLs are replaced with /navidrome_segment/<song_id>/<index> paths."""
        from pikaraoke.routes.navidrome import _rewrite_manifest

        manifest, _ = _rewrite_manifest(
            SAMPLE_HLS_MANIFEST_ABSOLUTE, "http://navidrome:4533", "song-1"
        )
        segment_lines = [l for l in manifest.splitlines() if l.startswith("/navidrome_segment/")]

        assert segment_lines == ["/navidrome_segment/song-1/0", "/navidrome_segment/song-1/1"]

    def test_rewrites_relative_segment_urls_to_proxy_paths(self):
        """Relative segment URLs are resolved against the Navidrome base and then proxied."""
        from pikaraoke.routes.navidrome import _rewrite_manifest

        manifest, _ = _rewrite_manifest(
            SAMPLE_HLS_MANIFEST_RELATIVE, "http://navidrome:4533", "song-1"
        )
        segment_lines = [l for l in manifest.splitlines() if l.startswith("/navidrome_segment/")]

        assert segment_lines == ["/navidrome_segment/song-1/0", "/navidrome_segment/song-1/1"]

    def test_returns_original_absolute_segment_urls_in_order(self):
        """The returned segment list contains the original Navidrome URLs in manifest order."""
        from pikaraoke.routes.navidrome import _rewrite_manifest

        _, segments = _rewrite_manifest(
            SAMPLE_HLS_MANIFEST_ABSOLUTE, "http://navidrome:4533", "song-1"
        )

        assert segments == [
            "http://navidrome:4533/rest/stream.view?id=song-1&index=0",
            "http://navidrome:4533/rest/stream.view?id=song-1&index=1",
        ]

    def test_resolves_relative_segment_urls_against_navidrome_base(self):
        """Relative segment URLs are resolved to full Navidrome URLs in the returned list."""
        from pikaraoke.routes.navidrome import _rewrite_manifest

        _, segments = _rewrite_manifest(
            SAMPLE_HLS_MANIFEST_RELATIVE, "http://navidrome:4533", "song-1"
        )

        assert all(s.startswith("http://navidrome:4533") for s in segments)


class TestNavidromeHlsRoute:
    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_returns_manifest_with_hls_content_type(self, mock_requests, mock_get_instance, client):
        """GET /navidrome_hls/<song_id> returns a manifest with HLS content type."""
        mock_get_instance.return_value = make_karaoke_mock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_HLS_MANIFEST_ABSOLUTE
        mock_requests.return_value = mock_resp

        response = client.get("/navidrome_hls/song-1")

        assert response.status_code == 200
        assert "mpegurl" in response.content_type.lower()

    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_manifest_segment_urls_point_to_pikaraoke_proxy(
        self, mock_requests, mock_get_instance, client
    ):
        """Segment lines in the returned manifest reference /navidrome_segment/, not Navidrome directly."""
        mock_get_instance.return_value = make_karaoke_mock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_HLS_MANIFEST_ABSOLUTE
        mock_requests.return_value = mock_resp

        response = client.get("/navidrome_hls/song-1")

        manifest = response.data.decode()
        segment_lines = [l for l in manifest.splitlines() if not l.startswith("#") and l.strip()]
        assert all(l.startswith("/navidrome_segment/") for l in segment_lines)
        assert "navidrome:4533" not in manifest

    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_passes_bitrate_128_to_navidrome(self, mock_requests, mock_get_instance, client):
        """Navidrome is called with bitRate=128 to cap bandwidth usage."""
        mock_get_instance.return_value = make_karaoke_mock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_HLS_MANIFEST_ABSOLUTE
        mock_requests.return_value = mock_resp

        client.get("/navidrome_hls/song-1")

        call_params = mock_requests.call_args[1]["params"]
        assert call_params["bitRate"] == 128

    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_stores_segment_urls_for_segment_proxy(self, mock_requests, mock_get_instance, client):
        """Fetching a manifest populates _segment_urls so the segment proxy can look them up."""
        mock_get_instance.return_value = make_karaoke_mock()
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_HLS_MANIFEST_ABSOLUTE
        mock_requests.return_value = mock_resp

        client.get("/navidrome_hls/song-1")

        assert navidrome_module._segment_urls["song-1"] == [
            "http://navidrome:4533/rest/stream.view?id=song-1&index=0",
            "http://navidrome:4533/rest/stream.view?id=song-1&index=1",
        ]

    @patch("pikaraoke.routes.navidrome.get_karaoke_instance")
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_returns_502_on_navidrome_connection_error(
        self, mock_requests, mock_get_instance, client
    ):
        """GET /navidrome_hls/<song_id> returns 502 when Navidrome is unreachable."""
        mock_get_instance.return_value = make_karaoke_mock()
        mock_requests.side_effect = req.RequestException("connection refused")

        response = client.get("/navidrome_hls/song-1")

        assert response.status_code == 502


class TestNavidromeSegmentRoute:
    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_proxies_segment_bytes_from_navidrome(self, mock_requests, client):
        """GET /navidrome_segment/<song_id>/<index> returns the raw audio bytes from Navidrome."""
        navidrome_module._segment_urls["song-1"] = [
            "http://navidrome:4533/rest/stream.view?id=song-1&index=0"
        ]
        mock_resp = MagicMock()
        mock_resp.content = b"audio bytes"
        mock_resp.headers = {"Content-Type": "audio/mpeg"}
        mock_requests.return_value = mock_resp

        response = client.get("/navidrome_segment/song-1/0")

        assert response.status_code == 200
        assert response.data == b"audio bytes"

    def test_returns_404_for_unknown_song_id(self, client):
        """GET /navidrome_segment for a song that was never loaded returns 404."""
        response = client.get("/navidrome_segment/unknown-song/0")

        assert response.status_code == 404

    def test_returns_404_for_out_of_bounds_index(self, client):
        """GET /navidrome_segment with an index beyond the segment list returns 404."""
        navidrome_module._segment_urls["song-1"] = [
            "http://navidrome:4533/rest/stream.view?id=song-1&index=0"
        ]

        response = client.get("/navidrome_segment/song-1/5")

        assert response.status_code == 404

    @patch("pikaraoke.routes.navidrome.requests.get")
    def test_returns_502_on_navidrome_connection_error(self, mock_requests, client):
        """GET /navidrome_segment returns 502 when Navidrome is unreachable."""
        navidrome_module._segment_urls["song-1"] = [
            "http://navidrome:4533/rest/stream.view?id=song-1&index=0"
        ]
        mock_requests.side_effect = req.RequestException("connection refused")

        response = client.get("/navidrome_segment/song-1/0")

        assert response.status_code == 502
