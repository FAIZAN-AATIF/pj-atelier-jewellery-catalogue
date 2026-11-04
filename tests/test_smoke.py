"""End-to-end smoke tests for the PJ catalogue API."""
import os

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-password")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_pj_catalogue.db")

from fastapi.testclient import TestClient
from app.main import app


def test_app_end_to_end():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        public_categories = client.get("/api/categories")
        assert public_categories.status_code == 200
        assert len(public_categories.json()) == 8

        public_products = client.get("/api/products")
        assert public_products.status_code == 200
        assert len(public_products.json()) == 800

        unauthenticated = client.post(
            "/api/categories",
            json={"name": "Should Not Be Created", "description": ""},
        )
        assert unauthenticated.status_code == 401

        login = client.post(
            "/api/auth/login",
            json={"username": os.environ["ADMIN_USERNAME"],
                  "password": os.environ["ADMIN_PASSWORD"]},
        )
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        stats = client.get("/api/admin/stats", headers=headers)
        assert stats.status_code == 200
        assert stats.json()["total_products"] == 800
        assert stats.json()["categories"] == 8

        admin_products = client.get("/api/admin/products", headers=headers)
        assert admin_products.status_code == 200
        assert len(admin_products.json()) == 800
