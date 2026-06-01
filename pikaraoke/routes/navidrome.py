"""Navidrome/Subsonic music streaming integration routes."""

import logging
import random
import time
from urllib.parse import urljoin

import requests
from flask import Response, jsonify
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance

navidrome_bp = Blueprint("navidrome", __name__)

_SUBSONIC_VERSION = "1.16.1"
_CLIENT_NAME = "pikaraoke"
_CACHE_TTL = 3600

_playlist_cache: dict = {"entries": [], "fetched_at": 0.0, "playlist_id": None}
_segment_urls: dict[str, list[str]] = {}


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


def _rewrite_manifest(
    manifest_text: str, navidrome_base: str, song_id: str
) -> tuple[str, list[str]]:
    """Parse an HLS manifest, replace segment URLs with PiKaraoke proxy paths.

    Returns the rewritten manifest string and the ordered list of original Navidrome
    segment URLs so the segment proxy can look them up by index.
    """
    base = navidrome_base.rstrip("/") + "/"
    lines = manifest_text.splitlines()
    rewritten = []
    segments = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            rewritten.append(line)
        else:
            full_url = stripped if stripped.startswith("http") else urljoin(base, stripped)
            segments.append(full_url)
            rewritten.append(f"/navidrome_segment/{song_id}/{len(segments) - 1}")
    return "\n".join(rewritten), segments


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


@navidrome_bp.route("/navidrome_hls/<song_id>", methods=["GET"])
def navidrome_hls(song_id: str):
    """Proxy the HLS manifest for a Navidrome song, rewriting segment URLs through PiKaraoke.

    Credentials never reach the browser — all Navidrome requests are server-side.
    Audio is transcoded to 128kbps to keep bandwidth low for remote clients.
    """
    k = get_karaoke_instance()
    if not k.navidrome_url:
        return jsonify({"error": "Navidrome not configured"}), 404
    try:
        params = _auth_params(k)
        params["id"] = song_id
        params["bitRate"] = 128
        resp = requests.get(
            _subsonic_url(k, "hls.m3u8"),
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        manifest, segments = _rewrite_manifest(resp.text, k.navidrome_url, song_id)
        _segment_urls[song_id] = segments
        return manifest, 200, {"Content-Type": "application/vnd.apple.mpegurl"}
    except requests.RequestException as e:
        logging.error("Navidrome HLS manifest error: %s", e)
        return jsonify({"error": "Could not fetch HLS manifest"}), 502


@navidrome_bp.route("/navidrome_segment/<song_id>/<int:index>", methods=["GET"])
def navidrome_segment(song_id: str, index: int):
    """Proxy an HLS audio segment from Navidrome, keeping credentials server-side."""
    segments = _segment_urls.get(song_id, [])
    if index >= len(segments):
        return jsonify({"error": "Segment not found"}), 404
    try:
        resp = requests.get(segments[index], timeout=30)
        resp.raise_for_status()
        return Response(resp.content, content_type=resp.headers.get("Content-Type", "audio/mpeg"))
    except requests.RequestException as e:
        logging.error("Navidrome segment proxy error: %s", e)
        return jsonify({"error": "Could not fetch segment"}), 502
