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
    mock_resp.json.return_value = {
        "subsonic-response": {"playlist": {"entry": entries}}
    }
    return mock_resp


@pytest.fixture(autouse=True)
def reset_playlist_cache():
    navidrome_module._playlist_cache["entries"] = []
    navidrome_module._playlist_cache["fetched_at"] = 0.0
    navidrome_module._playlist_cache["playlist_id"] = None
    yield
    navidrome_module._playlist_cache["entries"] = []
    navidrome_module._playlist_cache["fetched_at"] = 0.0
    navidrome_module._playlist_cache["playlist_id"] = None


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
    def test_returns_song_id_and_title_from_playlist(self, mock_requests, mock_get_instance, client):
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
    def test_refreshes_cache_after_ttl_expires(self, mock_time, mock_requests, mock_get_instance, client):
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
    def test_refreshes_cache_when_playlist_id_changes(self, mock_requests, mock_get_instance, client):
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
    def test_returns_502_on_navidrome_connection_error(self, mock_requests, mock_get_instance, client):
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
