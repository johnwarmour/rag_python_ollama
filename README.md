# Local RAG System

A modular Retrieval-Augmented Generation system with a configurable LLM backend, served locally via Ollama. Upload documents, ask questions, get answers grounded in what you uploaded.


---

## Index

- [How it Works](#how-it-works)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Installation](#installation)
    - [Virtual Environment](#virtual-environment)
    - [Docker](#docker)
- [Running Tests](#running-tests)
- [Admin Setup](#admin-setup)
- [Extra Notes](#extra-notes)
    - [Persistent Storage](#persistent-storage)
    - [Resetting the Project](#resetting-the-project)
    - [Ollama on Linux Host](#ollama-on-linux-host)
    - [Changing Models](#changing-models)
    - [Rate Limiting](#rate-limiting)


---

## How it Works

An admin user curates a shared document library by uploading and embedding files. All users query against that shared library through a chat interface. The RAG chain retrieves relevant document chunks, builds context, and streams a response from the LLM.

The system runs two servers in one container: FastAPI handles all backend logic, and Streamlit serves the frontend.


---

## Features

**Role system (admin / user)**

- Two roles: `admin` and `user`. Admins manage the document library and user accounts. Regular users can only chat.
- No self-registration. Admins create user accounts from a panel in the sidebar. The first admin is bootstrapped directly via the command line (see [Admin Setup](#admin-setup)).

**Shared document library**

- Admins upload and embed documents into a shared public library. All users query against the same library.
- Supported formats: PDF, TXT, Markdown.
- Per-file delete and PDF preview available to admins in the sidebar.
- Upload failures are handled per-file — a single failed embed does not stop the remaining files from being processed.

**Chat interface**

- Streaming responses via Server-Sent Events, formatted as NDJSON.
- Retrieved source documents are shown alongside each response with page references and a link to open the original file.
- Supports thinking models — the LLM's reasoning is shown in a collapsible panel.
- Session chat history is maintained per user and persisted across page refreshes.

**Vector storage and retrieval**

- Documents are split into chunks, embedded with `bge-m3`, and stored in FAISS.
- Retrieval uses similarity search to surface the most relevant chunks across documents. MMR (Max Marginal Relevance) was tried, but for the testing use case lack of nuance in responses was an issue. MMR may well be a better strategy for a different document set and/or different response requirements.
- The RAG chain summarizes conversation history into a standalone query before retrieval.

**Security**

- Prompt injection detection — queries are checked against common injection patterns before reaching the LLM. Suspicious queries are rejected with a 400 response.
- The system prompt explicitly instructs the model to treat user input as a question only, never as instructions that override its behavior.
- Rate limiting is built in but disabled by default (appropriate for local/trusted deployments). It can be enabled for external API use — see [Rate Limiting](#rate-limiting).

**FastAPI backend**

- Handles file uploads, embedding, deletion, authentication, and LLM streaming.
- Admin-only endpoints are enforced server-side and return 403 for unauthorized access.

**Docker**

- Runs both FastAPI and Streamlit in a single container.
- Connects to Ollama running on the host machine via `host.docker.internal`.


---

## Tech Stack

- LangChain
- FastAPI
- Streamlit
- Docker
- Ollama
    - Configurable chat LLM (default: `gemma3:12b`)
    - bge-m3 (embeddings)
- FAISS
- SQLite-3
- bcrypt
- LangSmith (optional tracing)


---

## Installation

### Virtual Environment

1. Clone the repository:
    ```bash
    git clone --depth 1 https://github.com/johnwarmour/rag_python_ollama.git
    cd rag-with-gemma3
    ```

2. Create and activate a virtual environment:
    ```bash
    python -m venv venv
    source venv/bin/activate       # Linux / macOS
    # venv\Scripts\activate        # Windows
    pip install -r requirements.txt
    ```

3. Optionally configure LangSmith tracing. Create `server/.env`:
    ```ini
    LANGCHAIN_TRACING_V2=true
    LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
    LANGCHAIN_API_KEY="your_api_key"
    LANGCHAIN_PROJECT="rag-with-gemma3"
    ```

4. Start the FastAPI server:
    ```bash
    cd server
    uvicorn server:app --port 8000
    ```

5. Start the Streamlit app in a separate terminal:
    ```bash
    streamlit run app.py
    ```

6. Open:
    - Streamlit UI: [http://localhost:8501](http://localhost:8501)
    - FastAPI docs: [http://localhost:8000/docs](http://localhost:8000/docs)

After starting, follow the [Admin Setup](#admin-setup) steps to create the first admin account.


---

### Docker

```bash
# Build
docker build -t rag-gemma3:dev .

# Create container
docker create --name rag-gemma3-dev \
    -p 8000:8000 -p 8501:8501 \
    rag-gemma3:dev

# Optional: LangSmith tracing
#   -e LANGCHAIN_TRACING_V2=true \
#   -e LANGCHAIN_ENDPOINT="https://api.smith.langchain.com" \
#   -e LANGCHAIN_API_KEY="your_key" \
#   -e LANGCHAIN_PROJECT="rag-with-gemma3" \

# Start
docker start -a rag-gemma3-dev
```

Open the UI at [http://localhost:8501](http://localhost:8501).

#### Rebuild shortcut

```bash
docker rm -f rag-gemma3-dev && \
docker build -t rag-gemma3:dev . && \
docker run -d --name rag-gemma3-dev -p 8000:8000 -p 8501:8501 rag-gemma3:dev
```


---

## Running Tests

Tests cover the database layer (`sq_db.py`), file operations (`files.py`), and FastAPI endpoints (`server.py`). No Ollama connection is required — LLM components are mocked.

Requires the virtual environment from [Installation](#virtual-environment). Then install test dependencies and run:

```bash
pip install -r requirements-test.txt
pytest
```

Run a specific module or with verbose output:

```bash
pytest tests/test_sq_db.py -v
pytest tests/test_server.py -v
```


---

## Admin Setup

There is no registration screen. The first admin account must be created directly from the command line.

**Virtual environment:**
```bash
cd server
python sq_db.py --bootstrap
```

**Docker (exec into a running container):**
```bash
docker exec -it rag-gemma3-dev bash
cd /fastAPI
python sq_db.py --bootstrap
```

The script prompts for a user ID, display name, and password. Once created, log in through the UI. From the sidebar, you can upload documents and manage regular user accounts.


---

## Extra Notes

### Persistent Storage

By default, all data lives inside the container and is lost when the container is removed. To persist it, mount these paths when creating the container:

```bash
docker create --name rag-gemma3-dev \
    -e ENV_TYPE=dev \
    -p 8000:8000 -p 8501:8501 \
    -v /your/local/uploads:/fastAPI/user_uploads \
    -v /your/local/faiss:/fastAPI/user_faiss \
    -v /your/local/data.db:/fastAPI/user_data.db \
    -v /your/local/app.log:/fastAPI/app.log \
    rag-gemma3:dev
```

| Container path | Contents |
|----------------|----------|
| `/fastAPI/user_uploads` | Uploaded files |
| `/fastAPI/user_faiss` | FAISS vector index |
| `/fastAPI/user_data.db` | SQLite database (users, file records) |
| `/fastAPI/app.log` | Server logs |

> **Note:** `user_data.db` is also copied into the image at build time if it exists in `server/` on the host, allowing you to persist your users on rebuilds. Add it to a `.dockerignore` if you want a clean database on every build.


### Resetting the Project

Clear Python cache:
```bash
# Linux / macOS
find . -type d -name "__pycache__" -exec rm -r {} +

# Windows
Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
```

Clear all user data:
```bash
rm -rf server/user_uploads/ server/user_faiss/ server/user_data.db
```

Recreate a blank database and bootstrap a fresh admin:
```bash
cd server
python sq_db.py --bootstrap
```


### Ollama on Linux Host

Docker does not resolve `host.docker.internal` automatically on Linux. Add this flag to your `docker create` command:

```bash
--add-host=host.docker.internal:host-gateway
```


### Changing Models

All model names and parameters are set in [`server/llm_system/config.py`](./server/llm_system/config.py). Change `LLM_CHAT_MODEL_NAME`, `EMB_MODEL_NAME`, or other constants there.

If using Docker, make the same changes in the [`docker/dev_*`](./docker/) files, since those replace the core files at build time.

To test sub-modules in isolation:
```bash
cd server
python -m llm_system.utils.loader
```


### Rate Limiting

Rate limiting is disabled by default, which is appropriate when running locally with a trusted user base and a local LLM (no per-token cost). When switching to an external API such as OpenAI or Anthropic, enable it to control costs.

In [`server/llm_system/config.py`](./server/llm_system/config.py):

```python
RATE_LIMIT_ENABLED: bool = True          # Enable rate limiting
RATE_LIMIT_REQUESTS_PER_MINUTE: int = 10 # Max requests per user per minute
```

Limits are enforced per `user_id` on the `/rag` endpoint using a sliding one-minute window. Requests over the limit receive a `429 Too Many Requests` response. No external dependencies are required.


---

## Credits
The starting codebase was from https://github.com/Bbs1412/rag-with-gemma3


## License

[![License](https://img.shields.io/badge/License%20-GNU%20--%20GPL%20v3.0-blue.svg?logo=GNU)](https://www.gnu.org/licenses/gpl-3.0)

Licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for details.


## Contact

[johnwarmour@gmail.com](mailto:johnwarmour@gmail.com)
