"""Navidrome/Subsonic music streaming integration routes."""

import logging
import random
import time

import requests
from flask import jsonify
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance

navidrome_bp = Blueprint("navidrome", __name__)

_SUBSONIC_VERSION = "1.16.1"
_CLIENT_NAME = "pikaraoke"
_CACHE_TTL = 3600

_playlist_cache: dict = {"entries": [], "fetched_at": 0.0, "playlist_id": None}


def _auth_params(k) -> dict:
    return {
        "u": k.navidrome_username,
        "p": k.navidrome_password,
        "v": _SUBSONIC_VERSION,
        "c": _CLIENT_NAME,
        "f": "json",
    }


def _subsonic_url(k, endpoint: str) -> str:
    return f"{k.navidrome_url.rstrip('/')}/rest/{endpoint}"


def _fetch_playlist_entries(k) -> list[dict]:
    params = _auth_params(k)
    params["id"] = k.navidrome_playlist_id
    resp = requests.get(
        _subsonic_url(k, "getPlaylist.view"),
        params=params,
        timeout=5,
    )
    resp.raise_for_status()
    data = resp.json()
    entries = data["subsonic-response"]["playlist"].get("entry", [])
    # Subsonic returns a dict (not list) when there is only one entry
    if isinstance(entries, dict):
        entries = [entries]
    return entries


def _get_cached_entries(k) -> list[dict]:
    now = time.time()
    stale = now - _playlist_cache["fetched_at"] > _CACHE_TTL
    playlist_changed = _playlist_cache["playlist_id"] != k.navidrome_playlist_id
    if stale or playlist_changed:
        _playlist_cache["entries"] = _fetch_playlist_entries(k)
        _playlist_cache["fetched_at"] = now
        _playlist_cache["playlist_id"] = k.navidrome_playlist_id
    return _playlist_cache["entries"]


@navidrome_bp.route("/navidrome_playlists", methods=["GET"])
def navidrome_playlists():
    """List all playlists available on the configured Navidrome server."""
    k = get_karaoke_instance()
    if not k.navidrome_url or not k.navidrome_username:
        return jsonify([])
    try:
        resp = requests.get(
            _subsonic_url(k, "getPlaylists.view"),
            params=_auth_params(k),
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        playlists = data["subsonic-response"]["playlists"].get("playlist", [])
        # Subsonic returns a dict (not list) when there is only one playlist
        if isinstance(playlists, dict):
            playlists = [playlists]
        return jsonify([{"id": p["id"], "name": p["name"]} for p in playlists])
    except requests.RequestException as e:
        logging.error("Navidrome connection error: %s", e)
        return jsonify({"error": "Could not connect to Navidrome"}), 502
    except (KeyError, ValueError) as e:
        logging.error("Navidrome response parse error: %s", e)
        return jsonify({"error": "Unexpected response from Navidrome"}), 502


@navidrome_bp.route("/navidrome_playlist", methods=["GET"])
def navidrome_playlist():
    """Return a shuffled list of stream URLs for the configured Navidrome playlist.

    Credentials are embedded in each URL using standard Subsonic auth params so the
    browser can stream directly from Navidrome without proxying through PiKaraoke.
    """
    k = get_karaoke_instance()
    if not k.navidrome_url or not k.navidrome_playlist_id:
        return jsonify([])
    try:
        entries = _fetch_playlist_entries(k)
        auth_suffix = (
            f"u={k.navidrome_username}&p={k.navidrome_password}"
            f"&v={_SUBSONIC_VERSION}&c={_CLIENT_NAME}"
        )
        base = k.navidrome_url.rstrip("/")
        stream_urls = [
            f"{base}/rest/stream.view?id={entry['id']}&{auth_suffix}" for entry in entries
        ]
        random.shuffle(stream_urls)
        return jsonify(stream_urls)
    except requests.RequestException as e:
        logging.error("Navidrome connection error: %s", e)
        return jsonify({"error": "Could not connect to Navidrome"}), 502
    except (KeyError, ValueError) as e:
        logging.error("Navidrome response parse error: %s", e)
        return jsonify({"error": "Unexpected response from Navidrome"}), 502


@navidrome_bp.route("/navidrome_next", methods=["GET"])
def navidrome_next():
    """Return a random song from the configured Navidrome playlist.

    Uses a server-side cache to avoid fetching the playlist on every song change.
    """
    k = get_karaoke_instance()
    if not k.navidrome_url or not k.navidrome_playlist_id:
        return jsonify({})
    try:
        entries = _get_cached_entries(k)
        if not entries:
            return jsonify({})
        entry = random.choice(entries)
        return jsonify({"id": entry["id"], "title": entry["title"]})
    except requests.RequestException as e:
        logging.error("Navidrome connection error: %s", e)
        return jsonify({"error": "Could not connect to Navidrome"}), 502
    except (KeyError, ValueError) as e:
        logging.error("Navidrome response parse error: %s", e)
        return jsonify({"error": "Unexpected response from Navidrome"}), 502
