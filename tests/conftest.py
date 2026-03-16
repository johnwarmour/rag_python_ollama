"""
Shared pytest fixtures for the RAG with Gemma3 test suite.

Isolation strategy:
- sq_db: monkeypatch DB_PATH to a temp file per test
- files: monkeypatch UPLOADS_PATH to a temp dir per test
- server: patch all LLM/vector-DB symbols before TestClient runs the lifespan
"""

import sys
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

# Make server/ importable with bare module names (sq_db, files, logger, etc.)
sys.path.insert(0, str(Path(__file__).parent.parent / "server"))

# Mock fitz (PyMuPDF) before files.py is imported — only get_pdf_iframe uses it
# and that function is not tested here.
sys.modules.setdefault("fitz", MagicMock())

# Suppress app.log writes and noisy logging during tests
logging.disable(logging.CRITICAL)

import pytest


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Redirect sq_db.DB_PATH to a fresh temp SQLite file for one test."""
    import sq_db
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(sq_db, "DB_PATH", db_file)
    sq_db.create_tables()
    yield db_file


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    FastAPI TestClient with:
    - Isolated SQLite DB (sq_db.DB_PATH → tmp file)
    - Isolated uploads dir (files.UPLOADS_PATH → tmp dir)
    - All LLM/vector-DB components replaced with MagicMocks

    No Ollama connection is required.
    """
    import sq_db
    import files as files_module

    # Redirect SQLite DB
    db_file = tmp_path / "server_test.db"
    monkeypatch.setattr(sq_db, "DB_PATH", db_file)

    # Redirect file uploads
    uploads_dir = tmp_path / "uploads"
    monkeypatch.setattr(files_module, "UPLOADS_PATH", str(uploads_dir))

    # Build mocks
    mock_vector_db = MagicMock()
    mock_vector_db.get_retriever.return_value = MagicMock()
    mock_vector_db.get_vector_store.return_value = MagicMock()

    mock_history_store = MagicMock()
    mock_history_store.get_session_history.return_value = None
    mock_history_store.clear_session_history.return_value = True

    with patch("server.get_llm", return_value=MagicMock()), \
         patch("server.get_output_parser", return_value=MagicMock()), \
         patch("server.VectorDB", return_value=mock_vector_db), \
         patch("server.HistoryStore", return_value=mock_history_store), \
         patch("server.build_rag_chain", return_value=MagicMock()):

        from starlette.testclient import TestClient
        import server as server_module

        with TestClient(server_module.app) as c:
            yield c
