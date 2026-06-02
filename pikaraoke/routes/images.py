"""Image serving routes for QR code and logo."""
import mimetypes
import os

import flask_babel
from flask import flash, jsonify, redirect, request, send_file, url_for
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance, is_admin
from pikaraoke.lib.get_platform import get_data_directory

_ = flask_babel.gettext

images_bp = Blueprint("images", __name__)

_ALLOWED_LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


@images_bp.route("/qrcode")
def qrcode():
    """Get QR code image for the web interface URL."""
    k = get_karaoke_instance()
    return send_file(k.qr_code_path, mimetype="image/png")


@images_bp.route("/logo")
def logo():
    """Get the PiKaraoke logo image."""
    k = get_karaoke_instance()
    mime = mimetypes.guess_type(k.logo_path)[0] or "image/png"
    return send_file(os.path.abspath(k.logo_path), mimetype=mime)


@images_bp.route("/logo", methods=["POST"])
def upload_logo():
    """Upload a custom logo image (admin only)."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    if "logo" not in request.files or not request.files["logo"].filename:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["logo"]
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in _ALLOWED_LOGO_EXTENSIONS:
        return jsonify({"error": "Invalid file type"}), 400

    dest = os.path.join(get_data_directory(), f"logo.{ext}")
    file.save(dest)

    k = get_karaoke_instance()
    k.logo_path = dest
    k.preferences.set("logo_path", dest, section="SYSTEM")

    flash(_("Logo updated successfully!"), "is-success")
    return redirect(url_for("info.info"))
