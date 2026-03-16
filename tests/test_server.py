"""Tests for server/server.py — FastAPI endpoint layer.

All tests use the `client` fixture from conftest.py, which:
- Isolates the SQLite DB to a temp file
- Isolates file uploads to a temp dir
- Mocks all LLM/vector-DB components (no Ollama required)

Admin/regular users are seeded directly via sq_db.add_user() rather than
through the API, to avoid circular dependencies in fixtures.
"""

import pytest
import sq_db


@pytest.fixture
def admin(client):
    """Create an admin user in the isolated DB. Returns credentials dict."""
    sq_db.add_user("admin1", "Admin One", "adminpass", role="admin")
    return {"user_id": "admin1", "password": "adminpass"}


@pytest.fixture
def regular_user(client, admin):
    """Create a regular user via the admin API endpoint. Returns credentials dict."""
    client.post("/admin/add_user", data={
        "admin_id": "admin1",
        "name": "Regular User",
        "user_id": "user1",
        "password": "userpass",
    })
    return {"user_id": "user1", "password": "userpass"}


# ==============================================================================
# Health Check
# ==============================================================================

def test_root_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "message" in resp.json()


# ==============================================================================
# POST /login
# ==============================================================================

def test_login_success_returns_user_id_name_role(client, admin):
    resp = client.post("/login", json={"login_id": "admin1", "password": "adminpass"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "admin1"
    assert body["name"] == "Admin One"
    assert body["role"] == "admin"


def test_login_wrong_password_returns_401(client, admin):
    resp = client.post("/login", json={"login_id": "admin1", "password": "wrong"})
    assert resp.status_code == 401
    assert "error" in resp.json()


def test_login_unknown_user_returns_401(client):
    resp = client.post("/login", json={"login_id": "nobody", "password": "pw"})
    assert resp.status_code == 401
    assert "error" in resp.json()


# ==============================================================================
# GET /uploads
# ==============================================================================

def test_uploads_returns_empty_list_for_new_user(client, admin):
    resp = client.get("/uploads", params={"user_id": "admin1"})
    assert resp.status_code == 200
    assert resp.json() == {"files": []}


def test_uploads_returns_active_files(client, admin):
    sq_db.add_file("admin1", "report.pdf")
    resp = client.get("/uploads", params={"user_id": "admin1"})
    assert resp.status_code == 200
    assert "report.pdf" in resp.json()["files"]


# ==============================================================================
# GET /admin/users
# ==============================================================================

def test_admin_get_users_returns_200_for_admin(client, admin, regular_user):
    resp = client.get("/admin/users", params={"admin_id": "admin1"})
    assert resp.status_code == 200
    assert "users" in resp.json()


def test_admin_get_users_returns_403_for_non_admin(client, admin, regular_user):
    resp = client.get("/admin/users", params={"admin_id": "user1"})
    assert resp.status_code == 403


def test_admin_get_users_excludes_admin_accounts(client, admin, regular_user):
    resp = client.get("/admin/users", params={"admin_id": "admin1"})
    user_ids = [u["user_id"] for u in resp.json()["users"]]
    assert "admin1" not in user_ids
    assert "user1" in user_ids


# ==============================================================================
# POST /admin/add_user
# ==============================================================================

def test_admin_add_user_success_returns_201(client, admin):
    resp = client.post("/admin/add_user", data={
        "admin_id": "admin1",
        "name": "New User",
        "user_id": "newuser",
        "password": "newpass",
    })
    assert resp.status_code == 201
    assert resp.json() == {"status": "success"}


def test_admin_add_user_returns_403_for_non_admin(client, admin, regular_user):
    resp = client.post("/admin/add_user", data={
        "admin_id": "user1",
        "name": "Sneaky",
        "user_id": "sneaky",
        "password": "pw",
    })
    assert resp.status_code == 403


def test_admin_add_user_returns_400_on_duplicate(client, admin, regular_user):
    resp = client.post("/admin/add_user", data={
        "admin_id": "admin1",
        "name": "Duplicate",
        "user_id": "user1",  # already exists
        "password": "pw",
    })
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_admin_add_user_new_user_can_log_in(client, admin):
    client.post("/admin/add_user", data={
        "admin_id": "admin1",
        "name": "Fresh User",
        "user_id": "freshuser",
        "password": "freshpass",
    })
    resp = client.post("/login", json={"login_id": "freshuser", "password": "freshpass"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


# ==============================================================================
# POST /admin/delete_user
# ==============================================================================

def test_admin_delete_user_success_returns_200(client, admin, regular_user):
    resp = client.post("/admin/delete_user", data={
        "admin_id": "admin1",
        "target_user_id": "user1",
    })
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}


def test_admin_delete_user_returns_403_for_non_admin(client, admin, regular_user):
    resp = client.post("/admin/delete_user", data={
        "admin_id": "user1",
        "target_user_id": "user1",
    })
    assert resp.status_code == 403


def test_admin_delete_user_returns_400_when_target_is_admin(client, admin):
    sq_db.add_user("admin2", "Admin Two", "pw", role="admin")
    resp = client.post("/admin/delete_user", data={
        "admin_id": "admin1",
        "target_user_id": "admin2",
    })
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_admin_delete_user_returns_404_for_unknown_user(client, admin):
    resp = client.post("/admin/delete_user", data={
        "admin_id": "admin1",
        "target_user_id": "nobody",
    })
    assert resp.status_code == 404


def test_admin_delete_user_user_cannot_log_in_after_deletion(client, admin, regular_user):
    client.post("/admin/delete_user", data={
        "admin_id": "admin1",
        "target_user_id": "user1",
    })
    resp = client.post("/login", json={"login_id": "user1", "password": "userpass"})
    assert resp.status_code == 401
