"""Navidrome/Subsonic music streaming integration routes."""

import logging
import random

import requests
from flask import jsonify
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance

navidrome_bp = Blueprint("navidrome", __name__)

_SUBSONIC_VERSION = "1.16.1"
_CLIENT_NAME = "pikaraoke"


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
