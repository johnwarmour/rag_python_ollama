"""Tests for server/sq_db.py — SQLite database layer."""

import sqlite3
import sq_db


# ==============================================================================
# User Management
# ==============================================================================

def test_add_user_returns_true(isolated_db):
    assert sq_db.add_user("u1", "Alice", "pw1") is True


def test_add_user_duplicate_returns_false(isolated_db):
    sq_db.add_user("u1", "Alice", "pw1")
    assert sq_db.add_user("u1", "Alice Again", "pw2") is False


def test_check_user_exists_true_after_add(isolated_db):
    sq_db.add_user("u1", "Alice", "pw1")
    assert sq_db.check_user_exists("u1") is True


def test_check_user_exists_false_for_unknown(isolated_db):
    assert sq_db.check_user_exists("nobody") is False


def test_authenticate_user_success(isolated_db):
    sq_db.add_user("u1", "Alice", "pw1", role="user")
    ok, name, role = sq_db.authenticate_user("u1", "pw1")
    assert ok is True
    assert name == "Alice"
    assert role == "user"


def test_authenticate_user_wrong_password(isolated_db):
    sq_db.add_user("u1", "Alice", "pw1")
    ok, msg, role = sq_db.authenticate_user("u1", "wrong")
    assert ok is False
    assert msg == "Incorrect password."
    assert role == ""


def test_authenticate_user_unknown_user(isolated_db):
    ok, msg, role = sq_db.authenticate_user("nobody", "pw")
    assert ok is False
    assert msg == "User does not exist."
    assert role == ""


def test_authenticate_user_sets_last_login(isolated_db):
    sq_db.add_user("u1", "Alice", "pw1")
    sq_db.authenticate_user("u1", "pw1")
    conn = sqlite3.connect(isolated_db)
    row = conn.execute("SELECT last_login FROM users WHERE user_id='u1'").fetchone()
    conn.close()
    assert row[0] is not None


def test_get_user_role_admin(isolated_db):
    sq_db.add_user("a1", "Admin", "pw", role="admin")
    assert sq_db.get_user_role("a1") == "admin"


def test_get_user_role_user(isolated_db):
    sq_db.add_user("u1", "User", "pw", role="user")
    assert sq_db.get_user_role("u1") == "user"


def test_get_user_role_missing_returns_empty_string(isolated_db):
    assert sq_db.get_user_role("nobody") == ""


def test_get_all_users_excludes_admins(isolated_db):
    sq_db.add_user("a1", "Admin", "pw", role="admin")
    sq_db.add_user("u1", "User One", "pw", role="user")
    sq_db.add_user("u2", "User Two", "pw", role="user")
    users = sq_db.get_all_users()
    user_ids = [u["user_id"] for u in users]
    assert "a1" not in user_ids
    assert "u1" in user_ids
    assert "u2" in user_ids


def test_get_all_users_empty_when_only_admins(isolated_db):
    sq_db.add_user("a1", "Admin", "pw", role="admin")
    assert sq_db.get_all_users() == []


def test_delete_user_returns_true_and_removes_user(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    assert sq_db.delete_user("u1") is True
    assert sq_db.check_user_exists("u1") is False


def test_delete_user_missing_returns_false(isolated_db):
    assert sq_db.delete_user("nobody") is False


def test_delete_user_cascades_to_uploads_and_embeddings(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    file_id = sq_db.add_file("u1", "doc.pdf")
    sq_db.add_embedding(file_id, "vec-1")

    sq_db.delete_user("u1")

    conn = sqlite3.connect(isolated_db)
    uploads = conn.execute("SELECT * FROM uploads WHERE user_id='u1'").fetchall()
    embeddings = conn.execute(
        "SELECT * FROM embeddings WHERE file_id=?", (file_id,)
    ).fetchall()
    conn.close()

    assert uploads == []
    assert embeddings == []


# ==============================================================================
# File Management
# ==============================================================================

def test_add_file_returns_positive_file_id(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    file_id = sq_db.add_file("u1", "doc.pdf")
    assert isinstance(file_id, int)
    assert file_id > 0


def test_get_user_files_returns_active_files_only(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    fid1 = sq_db.add_file("u1", "doc1.pdf")
    sq_db.add_file("u1", "doc2.pdf")
    sq_db.mark_file_removed("u1", fid1)
    result = sq_db.get_user_files("u1")
    assert result == ["doc2.pdf"]


def test_get_user_files_empty_for_new_user(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    assert sq_db.get_user_files("u1") == []


def test_get_file_id_by_name_returns_correct_id(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    fid = sq_db.add_file("u1", "doc.pdf")
    assert sq_db.get_file_id_by_name("u1", "doc.pdf") == fid


def test_get_file_id_by_name_returns_minus_one_when_missing(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    assert sq_db.get_file_id_by_name("u1", "ghost.pdf") == -1


def test_get_file_id_by_name_returns_minus_one_after_removed(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    fid = sq_db.add_file("u1", "doc.pdf")
    sq_db.mark_file_removed("u1", fid)
    assert sq_db.get_file_id_by_name("u1", "doc.pdf") == -1


def test_mark_file_removed_returns_true(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    fid = sq_db.add_file("u1", "doc.pdf")
    assert sq_db.mark_file_removed("u1", fid) is True


def test_mark_file_removed_makes_file_invisible(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    fid = sq_db.add_file("u1", "doc.pdf")
    sq_db.mark_file_removed("u1", fid)
    assert sq_db.get_user_files("u1") == []


def test_mark_file_removed_returns_false_for_wrong_id(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    assert sq_db.mark_file_removed("u1", 9999) is False


# ==============================================================================
# Embedding Management
# ==============================================================================

def test_add_embedding_returns_true(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    fid = sq_db.add_file("u1", "doc.pdf")
    assert sq_db.add_embedding(fid, "vec-1") is True


def test_get_file_embeddings_returns_correct_structure(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    fid = sq_db.add_file("u1", "doc.pdf")
    sq_db.add_embedding(fid, "vec-1")
    sq_db.add_embedding(fid, "vec-2")
    result = sq_db.get_file_embeddings("u1", "doc.pdf")
    assert result["file_id"] == fid
    assert sorted(result["embeddings"]) == ["vec-1", "vec-2"]


def test_get_file_embeddings_missing_file(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    result = sq_db.get_file_embeddings("u1", "ghost.pdf")
    assert result == {"file_id": -1, "embeddings": []}


def test_mark_embeddings_removed_returns_true(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    fid = sq_db.add_file("u1", "doc.pdf")
    sq_db.add_embedding(fid, "vec-1")
    assert sq_db.mark_embeddings_removed(["vec-1"]) is True


def test_mark_embeddings_removed_hides_from_query(isolated_db):
    sq_db.add_user("u1", "Alice", "pw")
    fid = sq_db.add_file("u1", "doc.pdf")
    sq_db.add_embedding(fid, "vec-1")
    sq_db.add_embedding(fid, "vec-2")
    sq_db.mark_embeddings_removed(["vec-1"])
    result = sq_db.get_file_embeddings("u1", "doc.pdf")
    assert result["embeddings"] == ["vec-2"]


def test_mark_embeddings_removed_empty_list_returns_false(isolated_db):
    assert sq_db.mark_embeddings_removed([]) is False
