"""Tests for server/files.py — disk file operations."""

import os
import pytest
import files


@pytest.fixture(autouse=True)
def patch_uploads(tmp_path, monkeypatch):
    """Redirect UPLOADS_PATH to a temp dir for every test in this module."""
    monkeypatch.setattr(files, "UPLOADS_PATH", str(tmp_path))


# ==============================================================================
# Folder Management
# ==============================================================================

def test_check_create_uploads_folder_creates_directory(tmp_path, monkeypatch):
    target = str(tmp_path / "new_uploads")
    monkeypatch.setattr(files, "UPLOADS_PATH", target)
    result = files.check_create_uploads_folder()
    assert os.path.isdir(target)
    assert result == target


def test_check_create_uploads_folder_is_idempotent(tmp_path):
    # UPLOADS_PATH already patched to tmp_path by autouse fixture
    files.check_create_uploads_folder()
    files.check_create_uploads_folder()  # should not raise


def test_create_user_uploads_folder_creates_subdir(tmp_path):
    result = files.create_user_uploads_folder("user1")
    assert result is True
    assert os.path.isdir(os.path.join(str(tmp_path), "user1"))


def test_create_user_uploads_folder_is_idempotent(tmp_path):
    assert files.create_user_uploads_folder("user1") is True
    assert files.create_user_uploads_folder("user1") is True


# ==============================================================================
# File Save / Delete
# ==============================================================================

def test_save_file_writes_bytes_to_disk(tmp_path):
    files.create_user_uploads_folder("u1")
    ok, name = files.save_file("u1", b"hello world", "doc.pdf")
    assert ok is True
    assert name == "doc.pdf"
    assert os.path.isfile(os.path.join(str(tmp_path), "u1", "doc.pdf"))


def test_save_file_sanitizes_spaces_in_name(tmp_path):
    files.create_user_uploads_folder("u1")
    ok, name = files.save_file("u1", b"x", "my file.pdf")
    assert ok is True
    assert name == "my_file.pdf"


def test_save_file_sanitizes_dots_in_basename(tmp_path):
    # Dots in the base name (before the final extension) are replaced with _
    files.create_user_uploads_folder("u1")
    ok, name = files.save_file("u1", b"x", "my.file.extra.pdf")
    assert ok is True
    assert name == "my_file_extra.pdf"


def test_save_file_conflict_adds_n_prefix(tmp_path):
    files.create_user_uploads_folder("u1")
    files.save_file("u1", b"first", "doc.pdf")
    ok, name = files.save_file("u1", b"second", "doc.pdf")
    assert ok is True
    assert name == "n_doc.pdf"


def test_save_file_repeated_conflict_stacks_n_prefix(tmp_path):
    files.create_user_uploads_folder("u1")
    files.save_file("u1", b"first", "doc.pdf")
    files.save_file("u1", b"second", "doc.pdf")
    ok, name = files.save_file("u1", b"third", "doc.pdf")
    assert ok is True
    assert name == "n_n_doc.pdf"


def test_delete_file_removes_existing_file(tmp_path):
    files.create_user_uploads_folder("u1")
    files.save_file("u1", b"content", "doc.pdf")
    result = files.delete_file("u1", "doc.pdf")
    assert result is True
    assert not os.path.exists(os.path.join(str(tmp_path), "u1", "doc.pdf"))


def test_delete_file_returns_false_for_missing_file(tmp_path):
    files.create_user_uploads_folder("u1")
    assert files.delete_file("u1", "ghost.pdf") is False


def test_delete_file_returns_false_for_wrong_user(tmp_path):
    files.create_user_uploads_folder("u1")
    files.save_file("u1", b"content", "doc.pdf")
    assert files.delete_file("u2", "doc.pdf") is False
