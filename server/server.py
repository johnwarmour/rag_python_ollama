# FastAPI server which will handle all the backend and GenAI aspects of the application
# uvicorn server:app --reload
# Avoid using --reload flag, because, LLMs will keep reloading and system will overheat.

import os
import mimetypes
from fastapi import FastAPI, File, UploadFile, Form, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

import json
import asyncio
import threading
import queue
import uuid
from pydantic import BaseModel
from contextlib import asynccontextmanager

# llm system imports:
from llm_system.core.llm import get_llm, get_output_parser  # Functions
from llm_system.core.llm import get_dummy_response          # Function
from llm_system.core.llm import get_dummy_response_stream   # Function
from llm_system.core.database import VectorDB               # Class
from llm_system.core.history import HistoryStore            # Class
from llm_system.chains.rag import build_rag_chain           # Function
from llm_system import config                               # Constants
from llm_system.core.ingestion import ingest_file           # Function

# Helper Modules:
import sq_db
import files

# Type hinting imports:
from langchain_core.vectorstores import VectorStore as T_VECTOR_STORE
from langchain_core.messages import BaseMessage as T_MESSAGE

import logger
log = logger.get_logger("rag_server")


# ------------------------------------------------------------------------------
# Task queue for non-blocking embed pipeline:
# ------------------------------------------------------------------------------

embed_tasks: dict[str, dict] = {}       # task_id → {"status": ..., ...}
embed_task_lock = threading.Lock()
embed_queue: queue.Queue = queue.Queue()


def embed_worker():
    """Processes embed jobs sequentially in a background thread.
    Sequential processing avoids FAISS race conditions on concurrent writes.
    """
    while True:
        task = embed_queue.get(block=True)
        task_id = task["task_id"]

        with embed_task_lock:
            embed_tasks[task_id]["status"] = "running"

        try:
            status, doc_ids, message = ingest_file(
                task["user_id"],
                task["file_path"],
                task["vector_db"],
                task["embeddings"],
            )

            if status and not doc_ids:
                with embed_task_lock:
                    embed_tasks[task_id] = {"status": "failed", "error": f"No embeddable content found in '{task['file_name']}'"}

            elif status:
                file_id = sq_db.get_file_id_by_name(user_id=task["user_id"], file_name=task["file_name"])
                for vid in doc_ids:
                    sq_db.add_embedding(file_id=file_id, vector_id=vid)
                log.info(f"[embed_worker] Completed '{task['file_name']}' ({len(doc_ids)} chunks)")
                with embed_task_lock:
                    embed_tasks[task_id] = {"status": "complete", "chunks": len(doc_ids)}

            else:
                log.error(f"[embed_worker] Failed '{task['file_name']}': {message}")
                with embed_task_lock:
                    embed_tasks[task_id] = {"status": "failed", "error": message}

        except Exception as e:
            log.error(f"[embed_worker] Unexpected error for '{task['file_name']}': {e}")
            with embed_task_lock:
                embed_tasks[task_id] = {"status": "failed", "error": str(e)}

        finally:
            embed_queue.task_done()


# ------------------------------------------------------------------------------
# Constants:
# ------------------------------------------------------------------------------

# UPLOADS_DIR: str = "user_uploads"
OLD_FILE_THRESHOLD: int = 3600 * 1  # 24 hours in seconds
# OLD_FILE_THRESHOLD: int = 20         # 1 min


# ------------------------------------------------------------------------------
# Auth helpers:
# ------------------------------------------------------------------------------

def is_admin(user_id: str) -> bool:
    """Returns True if the given user_id has the 'admin' role."""
    return sq_db.get_user_role(user_id) == 'admin'


# ------------------------------------------------------------------------------
# FastAPI Startup:
# ------------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Define the lifespan context manager for startup/shutdown"""

    # [ Startup ]
    log.info("[LifeSpan] Starting the server components.")

    app.state.llm_chat = get_llm(
        model_name=config.LLM_CHAT_MODEL_NAME,
        provider=config.LLM_PROVIDER,
        context_size=config.MAX_CONTENT_SIZE,
        temperature=config.LLM_CHAT_TEMPERATURE,
        verify_connection=config.VERIFY_LLM_CONNECTION
    )

    # app.state.llm_summary = get_llm(...)
    app.state.llm_summary = app.state.llm_chat

    app.state.output_parser = get_output_parser()
    app.state.vector_db = VectorDB(
        embed_model=config.EMB_MODEL_NAME,
        retriever_num_docs=config.DOCS_NUM_COUNT,
        verify_connection=config.VERIFY_EMB_CONNECTION,
    )
    app.state.history_store = HistoryStore()

    app.state.rag_chain = build_rag_chain(
        llm_chat=app.state.llm_chat,
        llm_summary=app.state.llm_summary,
        retriever=app.state.vector_db.get_retriever(),
        get_history_fn=app.state.history_store.get_session_history,
    )

    log.info("[LifeSpan] All LLM components initialized.")

    worker = threading.Thread(target=embed_worker, daemon=True)
    worker.start()
    log.info("[LifeSpan] Embed background worker started.")

    # sq_db.delete_database()
    sq_db.create_tables()

    # Files
    files.check_create_uploads_folder()
    files.delete_empty_user_folders()
    files.create_user_uploads_folder(user_id="public")  # shared library for admin uploads

    # [ Lifespan ]
    yield

    # [ Shutdown ]
    log.info("[LifeSpan] Shutting down LLM server...")
    # Add any cleanup part here
    # Like saving vector DB, or shutting down subprocesses


# Make one FastAPI app instance with the lifespan context manager
app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:5500",
        # "http://localhost:5500",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"]
)


# ------------------------------------------------------------------------------
# Basic API Endpoints:
# ------------------------------------------------------------------------------

@app.get("/")
async def root():
    """Root endpoint to check if the server is running."""
    return {
        "message": "Server is running",
    }


# Define data model for chat request
class BasicChatRequest(BaseModel):
    query: str
    session_id: str
    dummy: bool = False


@app.post("/simple")
async def simple(request: Request, chat_request: BasicChatRequest):
    """Endpoint to handle ont time generation queries.
    - Post request expects JSON `{"query": "", "session_id": "", "dummy":T/F}` structure.
    - Return JSON with `{"response": "", "session_id": ""}` structure.
    """

    llm = request.app.state.llm_chat | request.app.state.output_parser
    session_id = chat_request.session_id.strip() or "unknown_session"

    try:
        query = chat_request.query
        dummy = chat_request.dummy
        log.info(f"/simple Requested by '{session_id}'")

        if dummy:
            log.info(f"/simple Dummy response returned for '{session_id}'")
            return get_dummy_response()

        else:
            result = await llm.ainvoke(input=query)

            log.info(f"/simple Response generated for '{session_id}'.")
            return {"response": result, "session_id": session_id}

    except Exception as e:

        log.exception(f"/simple Error {e} for '{session_id}'")
        return JSONResponse(status_code=500, content={"error": str(e)})


# Make one streaming endpoint for the Simple LLM response:
class StreamChatRequest(BaseModel):
    query: str
    session_id: str
    dummy: bool = False


@app.post("/simple/stream")
async def chat_stream(request: Request, chat_request: StreamChatRequest):
    """Endpoint to handle streaming responses for one time generation queries.
    - Post request expects JSON `{"query": "", "session_id": "", "dummy":T/F}` structure.
    - Return NDJSON with types "metadata", "content", or "error".
    """
    llm = request.app.state.llm_chat | request.app.state.output_parser
    session_id = chat_request.session_id.strip() or "unknown_session"

    async def token_streamer():
        try:
            dummy = chat_request.dummy
            s = 'dummy' if dummy else 'real'
            log.info(f"/simple/stream {s} response requested by '{session_id}'")

            # Start be sending meta data first.
            yield json.dumps({
                "type": "metadata",
                "data": {"session_id": session_id}
            }) + "\n"
            # NDJSON (newline-delimited JSON) - Frontend will merge full response my splitting this

            #  Then send the actual response content:
            if dummy:
                # If dummy is True, stream dummy response
                resp = get_dummy_response_stream(
                    batch_tokens=config.BATCH_TOKEN_PS,
                    token_rate=config.TOKENS_PER_SEC
                )
                for chunk in resp:
                    if await request.is_disconnected():
                        log.warning(f"/simple/stream client disconnected for '{session_id}'")
                        break

                    yield json.dumps({
                        "type": "content",
                        "data": chunk
                    }) + "\n"

            else:
                async for chunk in llm.astream(chat_request.query):
                    if await request.is_disconnected():
                        log.warning(f"/simple/stream client disconnected for '{session_id}'")
                        break

                    yield json.dumps({
                        "type": "content",
                        "data": chunk
                    }) + "\n"

            # In the end, you can send some "Done" etc if u need some conditional logic
            # Server will auto send EOF to mark end of generator response.
            # yield json.dumps({
            #     "type": "end",
            #     "data": "done"
            # }) + "\n"
            log.info(f"/simple/stream Streaming completed for '{session_id}'")

        except Exception as e:
            log.exception(f"/simple/stream Error {e} for '{session_id}'")
            yield json.dumps({
                "type": "error",
                "data": str(e)
            }) + "\n"

    # Return a StreamingResponse with the token streamer generator (basically enable streaming)
    return StreamingResponse(token_streamer(), media_type="text/plain")


# ------------------------------------------------------------------------------
# Initialization End-points:
# ------------------------------------------------------------------------------

# Helper function to delete old files and embeddings:
def delete_old_files(user_id: str, time: int = OLD_FILE_THRESHOLD):
    """Function to delete old files and embeddings older than the specified time."""
    log.info(
        f"/delete Deleting old files and embeddings for user '{user_id}' older than {time} seconds")

    # Delete old files
    old_files = sq_db.get_old_files(user_id=user_id, time=time)
    if old_files['files']:
        log.info(f"/delete Removing old files for user '{user_id}': {old_files['files']}")

        for file in old_files['files']:
            status = files.delete_file(user_id=user_id, file_name=file)
            if status:
                file_id = sq_db.get_file_id_by_name(user_id=user_id, file_name=file)
                sq_db.mark_file_removed(user_id=user_id, file_id=file_id)

    # Delete old embeddings
    if old_files['embeddings']:
        log.info(f"/delete Removing old embeddings for user '{user_id}'")
        vs: VectorDB = app.state.vector_db
        db: T_VECTOR_STORE = vs.get_vector_store()
        resp = db.delete(old_files['embeddings'])

        # Save the changes to disk
        vs.save_db_to_disk()

        if resp == True:
            sq_db.mark_embeddings_removed(vector_ids=old_files['embeddings'])
            log.info(f"/delete Old embeddings removed for user '{user_id}'")
        else:
            log.error(f"/delete Failed to remove old embeddings for user '{user_id}': {resp}")
    else:
        log.info(f"/delete No old files found for user '{user_id}'")


# First end-point to call on client initialization:
class LoginRequest(BaseModel):
    login_id: str
    password: str


@app.post("/login")
async def login(request: Request, login_request: LoginRequest):
    """Endpoint to handle user login.
    + Client sends login_id and password for login
    + Based on it, server authenticates user.
    + user_id is retrieved (for now, it is same as login_id)
    + ? Based on user_id chat history of user is retrieved n returned.

    * Folder is created for user_id, older files are removed
    * Later on, will add on scheduled job to delete old items and will remove the old file deletion logic from here.

    - Post request expects JSON `{"login_id": "", "password": ""}` structure.
    - Return JSON with `{"user_id": "user_id", "chat_history": [user chat history]}` structure.
    """

    login_id = login_request.login_id.strip()
    password = login_request.password.strip()
    log.info(f"/login Requested by '{login_id}'")

    # Check if the user exists in the database
    status, msg, role = sq_db.authenticate_user(user_id=login_id, password=password)
    if status:
        user_id = login_id
        # Check if folder exists in UPLOADS_DIR with user_id
        files.create_user_uploads_folder(user_id=user_id)
        # Delete any older data if exists
        delete_old_files(user_id=user_id, time=OLD_FILE_THRESHOLD)
        return JSONResponse(content={"user_id": user_id, "name": msg, "role": role}, status_code=200)
    else:
        return JSONResponse(content={"error": msg}, status_code=401)

    # # For now, we will just return a dummy user_id
    # # In future, can implement actual user authentication and return a real user_id
    # user_id = login_id
    # log.info(f"/login requested by '{user_id}'")

    # # Check if folder exists in UPLOADS_DIR with user_id
    # files.create_user_uploads_folder(user_id=user_id)

    # # Old any older data if exists (older than 24 hours)
    # delete_old_files(user_id=user_id, time=OLD_FILE_THRESHOLD)

    # # Get the chat history for the user_id
    # hs: HistoryStore = request.app.state.history_store
    # history = hs.get_session_history(session_id=user_id)
    # if not history:
    #     log.info(f"/login No history found for user '{user_id}'")
    # else:
    #     log.info(f"/login History found for user '{user_id}' with {len(history.messages)} messages")

    # return {"user_id": user_id, "chat_history": history.messages}


# ------------------------------------------------------------------------------
# Chat History Endpoints:
# ------------------------------------------------------------------------------

# Endpoint to get chat history for user:
@app.post("/chat_history")
async def chat_history(user_id: str = Form(...)):
    """Endpoint to get chat history for user.
    - Post request expects `user_id` as form parameter.
    - Return JSON with `{"chat_history": [user chat history]}` or `{"error": "message"}` structure.
    """
    log.info(f"/chat_history Requested by '{user_id}'")
    hs: HistoryStore = app.state.history_store
    history = hs.get_session_history(session_id=user_id)

    if history:
        messages = []
        for msg in history.messages:
            msg: T_MESSAGE
            if msg.type == "ai":
                messages.append({"role": "assistant", "content": msg.text()})
            elif msg.type == "human":
                messages.append({"role": "human", "content": msg.text()})

        return JSONResponse(content={"chat_history": messages}, status_code=200)
    else:
        return JSONResponse(content={"error": "No chat history found"}, status_code=404)


# Endpoint /clear_chat_history to clear chat history for user:
@app.post("/clear_chat_history")
async def clear_chat_history(user_id: str = Form(...)):
    """Endpoint to clear chat history for user.
    - Post request expects `user_id` as form parameter.
    - Return JSON with `{"status": "success"}` or `{"error": "message"}` structure.
    """
    log.info(f"/clear_chat_history Requested by '{user_id}'")
    hs: HistoryStore = app.state.history_store
    status = hs.clear_session_history(session_id=user_id)

    if status:
        return JSONResponse(content={"status": "success"}, status_code=200)
    else:
        return JSONResponse(content={"error": "No history found to clear"}, status_code=404)


# ------------------------------------------------------------------------------
# File handling endpoints:
# ------------------------------------------------------------------------------

# Endpoint to receive file uploads:
@app.post("/upload")
async def upload_file(file: UploadFile = File(...), user_id: str = Form(...)):
    log.info(f"/upload Received file: {file.filename} from user: {user_id}")

    if not is_admin(user_id):
        return JSONResponse(content={"error": "Forbidden: admin only"}, status_code=403)

    filename = file.filename if file.filename else "unknown_file"

    # All uploads stored in the shared public library
    status, message = files.save_file(
        user_id="public",
        file_value_binary=await file.read(),
        file_name=filename
    )

    if status:
        filename = message
        sq_db.add_file(user_id="public", filename=filename)
        return JSONResponse(content={"message": filename}, status_code=200)
    else:
        log.error(f"/upload File upload failed for user {user_id}: {filename}")
        return JSONResponse(content={"error": message}, status_code=500)


# Endpoint to embed the uploaded file:
# takes user_id and file_name as input
class EmbedRequest(BaseModel):
    user_id: str
    file_name: str


@app.post("/embed")
async def embed_file(embed_request: EmbedRequest, request: Request):
    """Endpoint to queue an embed job. Returns task_id immediately (202 Accepted).
    - Post request expects JSON `{"user_id": "", "file_name": ""}` structure.
    - Return JSON with `{"task_id": "..."}` structure.
    """
    user_id = embed_request.user_id.strip()
    file_name = embed_request.file_name.strip()

    log.info(f"/embed Queued by '{user_id}' for file '{file_name}'")

    if not is_admin(user_id):
        return JSONResponse(content={"error": "Forbidden: admin only"}, status_code=403)

    task_id = str(uuid.uuid4())
    with embed_task_lock:
        embed_tasks[task_id] = {"status": "queued"}

    embed_queue.put({
        "task_id": task_id,
        "user_id": "public",
        "file_name": file_name,
        "file_path": files.get_file_path(user_id="public", file_name=file_name),
        "vector_db": request.app.state.vector_db,
        "embeddings": request.app.state.vector_db.get_embeddings(),
    })

    return JSONResponse(content={"task_id": task_id}, status_code=202)


@app.get("/embed/status/{task_id}")
async def embed_status(task_id: str, user_id: str = Query(...)):
    """Check status of an embed task.
    - Get request expects `user_id` as query parameter and `task_id` as path parameter.
    - Return JSON with task status dict or `{"error": "..."}` structure.
    """
    if not is_admin(user_id):
        return JSONResponse(content={"error": "Forbidden: admin only"}, status_code=403)

    with embed_task_lock:
        task = embed_tasks.get(task_id)

    if not task:
        return JSONResponse(content={"error": "Task not found"}, status_code=404)

    return JSONResponse(content=task, status_code=200)


# ------------------------------------------------------------------------------
# Data management endpoints:
# ------------------------------------------------------------------------------

# Endpoint /clear_my_files to clear all files in the shared public library (admin only):
@app.post("/clear_my_files")
async def clear_my_files(user_id: str = Form(...)):
    """Endpoint to clear all files in the shared public library.
    - Post request expects `user_id` as form parameter (used for admin auth).
    - Return JSON with `{"status": "success"}` or `{"error": "message"}` structure.
    """

    log.info(f"/clear_my_files Requested by '{user_id}'")

    if not is_admin(user_id):
        return JSONResponse(content={"error": "Forbidden: admin only"}, status_code=403)

    delete_old_files(user_id="public", time=1)
    return JSONResponse(content={"status": "success"}, status_code=200)


# Endpoint to delete a single file and its embeddings for a user:
@app.post("/delete_file")
async def delete_file(request: Request, user_id: str = Form(...), file_name: str = Form(...)):
    """Endpoint to delete a specific file and its embeddings from the shared public library.
    - Post request expects `user_id` (for admin auth) and `file_name` as form parameters.
    - Return JSON with `{"message": "..."}` or `{"error": "..."}` structure.
    """
    log.info(f"/delete_file Requested by '{user_id}' for file '{file_name}'")

    if not is_admin(user_id):
        return JSONResponse(content={"error": "Forbidden: admin only"}, status_code=403)

    # All files are stored under the shared "public" library
    file_data = sq_db.get_file_embeddings(user_id="public", file_name=file_name)
    file_id = file_data["file_id"]
    vector_ids = file_data["embeddings"]

    if file_id == -1:
        return JSONResponse(content={"error": "File not found"}, status_code=404)

    # Delete embeddings from vector store
    if vector_ids:
        vs: VectorDB = request.app.state.vector_db
        db: T_VECTOR_STORE = vs.get_vector_store()
        db.delete(vector_ids)
        vs.save_db_to_disk()
        sq_db.mark_embeddings_removed(vector_ids=vector_ids)

    # Delete physical file and mark db record as removed
    files.delete_file(user_id="public", file_name=file_name)
    sq_db.mark_file_removed(user_id="public", file_id=file_id)

    log.info(f"/delete_file Deleted '{file_name}' (requested by admin '{user_id}')")
    return JSONResponse(content={"message": f"'{file_name}' deleted successfully."}, status_code=200)


# End point to get all the files uploaded by user:
# This will be called first at initialization, and then after each file upload
@app.get("/uploads")
async def get_files(user_id: str = Query(...)):
    """Endpoint to get all the files uploaded by user.
    - Get request expects `user_id` as query parameter.
    - Return JSON with `{"files": ["file1", "file2", ...]}` structure.
    """
    log.info(f"/uploads Requested by '{user_id}'")
    files_list = sq_db.get_user_files(user_id=user_id)
    return {"files": files_list}


# Send pdf iframe based on user and file name:
# params: type=pdf/ppt/txt, user_id, file_name, num_pages
class FileIframeRequest(BaseModel):
    # type: Literal["pdf", "ppt", "txt"]
    user_id: str
    file_name: str
    num_pages: int = 5


@app.post("/iframe")
async def get_file_iframe(file_request: FileIframeRequest):
    """Endpoint to get the iframe for the file.
    - Post request expects JSON `{"user_id": "", "file_name": "", "num_pages": 5}` structure.
    - Return JSON with `{"iframe": "<iframe>...</iframe>"}` structure.
    """

    user_id = file_request.user_id.strip()
    file_name = file_request.file_name.strip()
    num_pages = file_request.num_pages

    log.info(f"/iframe Requested by '{user_id}' for file '{file_name}'")

    # Get the iframe for the requested file
    status, message = files.get_pdf_iframe(
        user_id=user_id,
        file_name=file_name,
        num_pages=num_pages
    )

    if status:
        return JSONResponse(content={"iframe": message}, status_code=200)
    else:
        return JSONResponse(content={"error": message}, status_code=404)


# Endpoint to serve an original uploaded file inline (so the browser can open it):
@app.get("/file")
async def serve_file(user_id: str = Query(...), file_name: str = Query(...)):
    """Endpoint to serve the original uploaded file for inline viewing.
    - Get request expects `user_id` and `file_name` as query parameters.
    - Returns the file with appropriate Content-Type so browsers can display it.
    """
    log.info(f"/file Requested by '{user_id}' for file '{file_name}'")
    file_path = files.get_file_path(user_id=user_id, file_name=file_name)

    if not os.path.isfile(file_path):
        return JSONResponse(content={"error": "File not found"}, status_code=404)

    media_type, _ = mimetypes.guess_type(file_name)
    if not media_type:
        media_type = "application/octet-stream"

    return FileResponse(
        path=file_path,
        media_type=media_type,
        headers={"Content-Disposition": f"inline; filename=\"{file_name}\""},
    )


# ------------------------------------------------------------------------------
# Admin Management Endpoints:
# ------------------------------------------------------------------------------

@app.get("/admin/users")
async def admin_get_users(admin_id: str = Query(...)):
    """Returns a list of all non-admin users.
    - Get request expects `admin_id` as query parameter.
    - Return JSON with `{"users": [{"user_id": "", "name": ""}, ...]}` structure.
    """
    log.info(f"/admin/users Requested by '{admin_id}'")

    if not is_admin(admin_id):
        return JSONResponse(content={"error": "Forbidden: admin only"}, status_code=403)

    users = sq_db.get_all_users(exclude_role='admin')
    return JSONResponse(content={"users": users}, status_code=200)


@app.post("/admin/add_user")
async def admin_add_user(
    admin_id: str = Form(...),
    name: str = Form(...),
    user_id: str = Form(...),
    password: str = Form(...),
):
    """Creates a new regular user account (admin only).
    - Post request expects form fields: `admin_id`, `name`, `user_id`, `password`.
    - Return JSON with `{"status": "success"}` or `{"error": "message"}` structure.
    """
    log.info(f"/admin/add_user Requested by '{admin_id}' to create user '{user_id}'")

    if not is_admin(admin_id):
        return JSONResponse(content={"error": "Forbidden: admin only"}, status_code=403)

    if sq_db.check_user_exists(user_id=user_id):
        return JSONResponse(content={"error": "User ID already exists"}, status_code=400)

    status = sq_db.add_user(user_id=user_id, name=name, password=password, role='user')
    if status:
        log.info(f"/admin/add_user User '{user_id}' created by admin '{admin_id}'")
        return JSONResponse(content={"status": "success"}, status_code=201)
    else:
        return JSONResponse(content={"error": "Failed to create user"}, status_code=500)


@app.post("/admin/delete_user")
async def admin_delete_user(admin_id: str = Form(...), target_user_id: str = Form(...)):
    """Deletes a regular user account and all associated data (admin only).
    - Post request expects form fields: `admin_id`, `target_user_id`.
    - Return JSON with `{"status": "success"}` or `{"error": "message"}` structure.
    """
    log.info(f"/admin/delete_user Requested by '{admin_id}' to delete '{target_user_id}'")

    if not is_admin(admin_id):
        return JSONResponse(content={"error": "Forbidden: admin only"}, status_code=403)

    if is_admin(target_user_id):
        return JSONResponse(content={"error": "Cannot delete an admin account"}, status_code=400)

    if not sq_db.check_user_exists(user_id=target_user_id):
        return JSONResponse(content={"error": "User not found"}, status_code=404)

    # Clear in-memory chat history for the target user
    hs: HistoryStore = app.state.history_store
    hs.clear_session_history(session_id=target_user_id)

    # Remove any files the user may have (effectively all, via time=1 cutoff)
    delete_old_files(user_id=target_user_id, time=1)

    # Hard-delete user row (CASCADE removes orphaned upload/embedding rows)
    sq_db.delete_user(target_user_id)

    log.info(f"/admin/delete_user User '{target_user_id}' deleted by admin '{admin_id}'")
    return JSONResponse(content={"status": "success"}, status_code=200)


# ------------------------------------------------------------------------------
# RAG Chain Endpoint:
# ------------------------------------------------------------------------------

# Create endpoint for rag:
# input = {
#     query: str,
#     session_id: str,
#     dummy: bool = False
# }
# Output will be streamed in same format as the simple/streaming chat endpoint.


class RagChatRequest(BaseModel):
    query: str
    session_id: str
    dummy: bool = False


@app.post("/rag")
async def rag(request: Request, chat_request: RagChatRequest):
    """Endpoint to handle RAG (Retrieval-Augmented Generation) queries.
    - Post request expects JSON `{"query": "", "session_id": "", "dummy":T/F}` structure.
    - Return NDJSON with types "metadata", "content", "context", or "error".
    """
    rag_chain = request.app.state.rag_chain
    session_id = chat_request.session_id.strip() or "unknown_session"

    async def token_streamer():
        try:
            dummy = chat_request.dummy
            log.info(f"/rag {'dummy' if dummy else 'real'} response requested by '{session_id}'")

            # Start by sending meta data first.
            yield json.dumps({
                "type": "metadata",
                "data": {"session_id": session_id}
            }) + "\n"

            if dummy:
                # If dummy is True, stream dummy response
                resp = get_dummy_response_stream(
                    batch_tokens=config.BATCH_TOKEN_PS,
                    token_rate=config.TOKENS_PER_SEC
                )
                for chunk in resp:
                    if await request.is_disconnected():
                        log.warning(f"/rag client disconnected for '{session_id}'")
                        break

                    yield json.dumps({
                        "type": "content",
                        "data": chunk
                    }) + "\n"

            else:
                # Search kwargs for the configurable retriever:
                search_kwargs = {
                    "k": 20,
                    "search_type": "similarity",
                    "filter": {
                        "$or": [
                            {"user_id": session_id},
                            {"user_id": "public"}
                        ]
                    },
                }

                async for chunk in rag_chain.astream(
                    input={"input": chat_request.query},
                    config={
                        "configurable": {
                            "session_id": session_id,
                            "search_kwargs": search_kwargs
                        }
                    }
                ):
                    if await request.is_disconnected():
                        log.warning(f"/rag client disconnected for '{session_id}'")
                        break

                    # there is answer/input/context
                    if "answer" in chunk:
                        yield json.dumps({
                            "type": "content",
                            "data": chunk["answer"]
                        }) + "\n"

                    elif "context" in chunk:
                        for document in chunk["context"]:
                            if await request.is_disconnected():
                                log.warning(f"/rag client disconnected for '{session_id}'")
                                break

                            # Hide user_id from metadata on UI
                            if "user_id" in document.metadata:
                                if document.metadata["user_id"] == "public":
                                    document.metadata["isPublicDocument"] = True
                                else:
                                    document.metadata["isPublicDocument"] = False
                                document.metadata.pop("user_id")

                            yield json.dumps({
                                "type": "context",
                                "data": {
                                    "metadata": document.metadata,
                                    "page_content": document.page_content
                                }
                            }) + "\n"

            log.info(f"/rag Streaming completed for '{session_id}'")

        except Exception as e:
            log.exception(f"/rag Error {e} for '{session_id}'")
            yield json.dumps({
                "type": "error",
                "data": str(e)
            }) + "\n"

    return StreamingResponse(token_streamer(), media_type="text/plain")


# ------------------------------------------------------------------------------
# Run the FastAPI server:
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    print("WARNING: Starting server without explicit uvicorn command. Not recommended for production use.")
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False
    )
