# Local RAG System

A modular Retrieval-Augmented Generation system with a configurable LLM backend, served locally via Ollama. Upload documents, ask questions, get answers grounded in what you uploaded.

[![HuggingFace Space](https://img.shields.io/badge/bhushan--songire/-rag--with--gemma3-ff8800.svg?logo=huggingface)](https://huggingface.co/spaces/bhushan-songire/rag-with-gemma3)

> The Hugging Face deployment uses Google Gemini-2.0-Flash-Lite instead of a local model, due to hosting constraints.


---

## Index

- [How it Works](#how-it-works)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Installation](#installation)
    - [Virtual Environment](#virtual-environment)
    - [Docker](#docker)
- [Admin Setup](#admin-setup)
- [Extra Notes](#extra-notes)
    - [Persistent Storage](#persistent-storage)
    - [Resetting the Project](#resetting-the-project)
    - [Ollama on Linux Host](#ollama-on-linux-host)
    - [Changing Models](#changing-models)


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
- Retrieval uses MMR (Max Marginal Relevance) to surface diverse, relevant chunks across documents.
- The RAG chain summarizes conversation history into a standalone query before retrieval.

**FastAPI backend**

- Handles file uploads, embedding, deletion, authentication, and LLM streaming.
- Admin-only endpoints are enforced server-side and return 403 for unauthorized access.

**Docker**

- Single Dockerfile supports both development (`ENV_TYPE=dev`) and deployment (`ENV_TYPE=deploy`) modes.
- Dev mode uses Ollama on the host machine. Deploy mode swaps in a Google Gemini API backend.


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
    git clone --depth 1 https://github.com/Bbs1412/rag-with-gemma3.git
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

The Dockerfile has two modes controlled by a build argument:

| Mode | `ENV_TYPE` | LLM backend | Ports |
|------|------------|-------------|-------|
| Development | `dev` | Ollama on host machine | 8000, 8501 |
| Deployment | `deploy` | Google Gemini API | 7860 |

#### Development

```bash
# Build
docker build --build-arg ENV_TYPE=dev -t rag-gemma3:dev .

# Create container
docker create --name rag-gemma3-dev \
    -e ENV_TYPE=dev \
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

#### Deployment

```bash
# Build
docker build --build-arg ENV_TYPE=deploy -t rag-gemma3:prod .

# Create container
docker create --name rag-gemma3-prod \
    -e ENV_TYPE=deploy \
    -e GOOGLE_API_KEY="your_google_api_key" \
    -p 7860:7860 \
    rag-gemma3:prod

# Start
docker start -a rag-gemma3-prod
```

Open the UI at [http://localhost:7860](http://localhost:7860).

#### Rebuild shortcut

```bash
# Dev
docker rm -f rag-gemma3-dev && \
docker build --build-arg ENV_TYPE=dev -t rag-gemma3:dev . && \
docker run -d --name rag-gemma3-dev -p 8000:8000 -p 8501:8501 rag-gemma3:dev
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

> **Note:** `user_data.db` is also copied into the image at build time if it exists in `server/` on the host. Add it to a `.dockerignore` if you want a clean database on every build.


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


---

## Contributions

Contributions and suggestions are welcome.


## License

[![License](https://img.shields.io/badge/License%20-GNU%20--%20GPL%20v3.0-blue.svg?logo=GNU)](https://www.gnu.org/licenses/gpl-3.0)

Licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE) for details.


## Contact

[bhushanbsongire@gmail.com](mailto:bhushanbsongire@gmail.com)
