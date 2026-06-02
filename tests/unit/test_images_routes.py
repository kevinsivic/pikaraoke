"""Tests for logo upload route."""

import io
from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask
from flask_babel import Babel

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.images import images_bp

ROUTE_PREFIX = "pikaraoke.routes.images"


@pytest.fixture
def app():
    test_app = Flask(__name__)
    test_app.secret_key = "test"
    Babel(test_app)
    test_app.register_blueprint(images_bp)
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_mocks(tmp_path):
    with (
        patch(f"{ROUTE_PREFIX}.get_karaoke_instance") as mock_get_instance,
        patch(f"{ROUTE_PREFIX}.is_admin", return_value=True),
        patch(f"{ROUTE_PREFIX}.get_data_directory", return_value=str(tmp_path)),
    ):
        mock_k = MagicMock()
        mock_get_instance.return_value = mock_k
        yield {"karaoke": mock_k, "data_dir": tmp_path}


class TestLogoUpload:
    """Tests for POST /logo."""

    def test_returns_403_when_not_admin(self, client):
        with patch(f"{ROUTE_PREFIX}.is_admin", return_value=False):
            response = client.post("/logo", data={}, content_type="multipart/form-data")
        assert response.status_code == 403

    def test_returns_400_when_no_file_field(self, client, admin_mocks):
        response = client.post("/logo", data={}, content_type="multipart/form-data")
        assert response.status_code == 400

    def test_returns_400_for_disallowed_extension(self, client, admin_mocks):
        data = {"logo": (io.BytesIO(b"fake"), "logo.txt")}
        response = client.post("/logo", data=data, content_type="multipart/form-data")
        assert response.status_code == 400

    def test_saves_png_to_data_directory(self, client, admin_mocks):
        data = {"logo": (io.BytesIO(b"\x89PNG"), "my_logo.png")}
        client.post("/logo", data=data, content_type="multipart/form-data", follow_redirects=False)

        assert (admin_mocks["data_dir"] / "logo.png").exists()

    def test_updates_karaoke_logo_path_on_success(self, client, admin_mocks):
        data = {"logo": (io.BytesIO(b"\x89PNG"), "my_logo.png")}
        client.post("/logo", data=data, content_type="multipart/form-data")

        expected = str(admin_mocks["data_dir"] / "logo.png")
        assert admin_mocks["karaoke"].logo_path == expected

    def test_persists_logo_path_to_preferences(self, client, admin_mocks):
        data = {"logo": (io.BytesIO(b"\x89PNG"), "my_logo.png")}
        client.post("/logo", data=data, content_type="multipart/form-data")

        expected = str(admin_mocks["data_dir"] / "logo.png")
        admin_mocks["karaoke"].preferences.set.assert_called_once_with(
            "logo_path", expected, section="SYSTEM"
        )

    def test_redirects_to_info_on_success(self, client, admin_mocks):
        data = {"logo": (io.BytesIO(b"\x89PNG"), "my_logo.png")}
        with patch(f"{ROUTE_PREFIX}.url_for", return_value="/info"):
            response = client.post(
                "/logo", data=data, content_type="multipart/form-data", follow_redirects=False
            )
        assert response.status_code == 302

    def test_accepts_jpg_extension(self, client, admin_mocks):
        data = {"logo": (io.BytesIO(b"JFIF"), "custom.jpg")}
        response = client.post("/logo", data=data, content_type="multipart/form-data")
        assert (admin_mocks["data_dir"] / "logo.jpg").exists()
        assert response.status_code != 400
