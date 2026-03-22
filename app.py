import json
import time
import requests
import streamlit as st
import urllib.parse
from typing import Optional, List, Literal

# import server.logger as logger


# ------------------------------------------------------------------------------
# Page Config:
# ------------------------------------------------------------------------------

st.set_page_config(
    page_title=st.secrets.app.site_name,
    page_icon="📚",
    layout='wide',
    initial_sidebar_state='expanded',
)


# ------------------------------------------------------------------------------
# Page consistent settings and initializations:
# ------------------------------------------------------------------------------

class Message:
    type: Literal['assistant', 'human']
    content: str
    filenames: Optional[List[str]]
    # List of filenames attached to the message
    # These names will be original file names, might be diff than actual saved on server
    # Hence, Chat-UI and sidebar might show same file with different names.

    def __init__(
        self, type: Literal['assistant', 'human'],
        content: str, filenames: Optional[List[str]] = None
    ):
        self.type = type
        self.content = content
        self.filenames = filenames


# Get user_id:
if "session_id" not in st.session_state:

    try:
        if requests.get(f"{st.secrets.server.ip_address}/").status_code != 200:
            raise Exception
    except:
        st.error(
            "Server is not reachable. Please check your connection or server status.", icon="🚫"
        )
        st.stop()

    with st.container(border=True):
        st.header("🔐 :orange[Login]")
        ip_user_id = st.text_input(
            "User ID:", placeholder="Enter your user ID here...",
            icon="👤", key="login_user_id"
        )
        ip_user_pw = st.text_input(
            "Password:", placeholder="Enter your password here...",
            type="password", icon="🔑", key="login_user_pw"
        )
        st.caption("User accounts are managed by an administrator.")

        if st.button("Login", type="primary"):
            ip_user_id = "_".join(ip_user_id.strip().lower().split(" "))
            ip_user_pw = ip_user_pw.strip()

            if not ip_user_id or not ip_user_pw:
                st.error("Please fill all the fields.", icon="🚫")
            else:
                # Send to server for login:
                try:
                    resp = requests.post(
                        f"{st.secrets.server.ip_address}/login",
                        json={"login_id": ip_user_id, "password": ip_user_pw}
                    )

                    if resp.status_code == 200:
                        session_id = resp.json().get("user_id")
                        st.session_state.session_id = session_id
                        st.session_state.name_of_user = resp.json().get("name", session_id)
                        st.session_state.role = resp.json().get("role", "user")

                        st.success("Login successful!", icon="✅")
                        st.rerun()
                    else:
                        st.error(resp.json().get("error", "Login failed."), icon="🚫")
                        st.stop()

                except requests.RequestException as e:
                    st.error(f"Error connecting to server: {e}", icon="🚫")
                    st.stop()

    st.stop()


if "initialized" not in st.session_state:
    # Initialize Logger:
    # st.session_state.logger = logger.get_logger(name="Streamlit")
    # log = st.session_state.logger
    # log.info("Streamlit initialized.")

    # Initialize the session with server::
    st.session_state.server_ip = st.secrets.server.ip_address
    try:
        resp = requests.post(
            f"{st.session_state.server_ip}/chat_history",
            data={"user_id": st.session_state.session_id}
        )
        if resp.status_code == 200:
            # Initialize messages:
            st.session_state.chat_history = [Message('assistant', "👋, How may I help you today?")]

            # Load old chat history (if):
            chat_hist = resp.json().get("chat_history", [])
            for msg in chat_hist:
                st.session_state.chat_history.append(Message(msg['role'], msg['content']))
        else:
            # log.error(f"Failed to initialize chat history: {resp.json().get('error', 'Unknown error')}")
            st.error(
                "Failed to initialize chat history. Please try again later.",
                icon="🚫"
            )
            st.stop()

    except requests.RequestException as e:
        # log.error(f"Error initializing server session: {e}")
        st.error(
            "Failed to connect to the server. Please check your connection or server status.",
            icon="🚫"
        )
        st.stop()

    # # Initialize messages:
    # st.session_state.chat_history = [
    #     Message('assistant', "👋, How may I help you today?"),
    #     # Message("human", "Help me in some thing...")
    # ]

    # Shared public library (admin-curated):
    st.session_state.user_uploads = requests.get(
        f"{st.session_state.server_ip}/uploads",
        params={"user_id": "public"}
    ).json().get("files", [])

    # Last resp retrieved docs:
    st.session_state.last_retrieved_docs = []

    # Key counter to reset file uploader after a successful upload run:
    st.session_state.uploader_key = 0

    # Set flag to true:
    st.session_state.initialized = True


# All variables in session state:
user_id = st.session_state.session_id
user_role = st.session_state.get("role", "user")
chat_history = st.session_state.chat_history
server_ip = st.session_state.server_ip
# log = st.session_state.logger


# ------------------------------------------------------------------------------
# Helper functions:
# ------------------------------------------------------------------------------


def write_as_ai(text):
    with st.chat_message(name='assistant', avatar='assistant'):
        st.markdown(text)


def write_as_human(text: str, filenames: Optional[List[str]] = None):
    with st.chat_message(name='user', avatar='user'):
        st.markdown(text)
        if filenames:
            files = ", ".join([f"`'{file}'`" for file in filenames])
            st.caption(f"🔗 Attached file(s): {files}.")


def upload_file(uploaded_file) -> tuple[bool, str]:
    """Upload the st attachment/uploaded file to the server and save it.
    Args:
        uploaded_file: The file object uploaded by the user.
    Returns:
        tuple: A tuple containing:
            - bool: True if the file was uploaded successfully, False otherwise.
            - str: The server file name or error message.
    """

    try:
        # POST to FastAPI
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
        data = {"user_id": user_id}
        response = requests.post(f"{server_ip}/upload", files=files, data=data)

        if response.status_code == 200:
            message = response.json().get("message", "")
            # log.info(f"File `{message}` uploaded successfully for user `{user_id}`.")
            return True, message
        else:
            message = response.json().get("error", "Unknown error")
            # log.error(
            # f"Failed to upload file `{uploaded_file.name}`: {message} for user `{user_id}`.")
            return False, message

    except Exception as e:
        # log.error(f"Error uploading file `{uploaded_file.name}`: {e} for user `{user_id}`.")
        return False, str(e)


def start_embed(file_name: str) -> tuple[bool, str]:
    """Queue an embed job on the server. Returns (success, task_id_or_error)."""
    try:
        response = requests.post(
            f"{server_ip}/embed",
            json={"user_id": user_id, "file_name": file_name},
            timeout=30,
        )
        if response.status_code == 202:
            return True, response.json()["task_id"]
        else:
            return False, response.json().get("error", "Unknown error")
    except Exception as e:
        return False, str(e)


def poll_embed_task(task_id: str) -> dict:
    """Check status of one embed task. Returns the task dict or an error dict."""
    try:
        response = requests.get(
            f"{server_ip}/embed/status/{task_id}",
            params={"user_id": user_id},
            timeout=10,
        )
        if response.status_code == 200:
            return response.json()
        return {"status": "failed", "error": response.json().get("error", "Unknown")}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def handle_uploaded_files(uploaded_files) -> bool:
    """Handle the uploaded files by uploading them to the server and embedding their content."""
    try:
        failed_files = []

        # --- Phase 1: Upload all files (fast) ---
        with st.status("Uploading files...", expanded=True) as status_box:
            uploaded = []   # [(original_name, server_file_name)]
            for i, file in enumerate(uploaded_files):
                st.write(f"📂 {i+1}/{len(uploaded_files)}: **{file.name}**")
                ok, result = upload_file(file)
                if ok:
                    uploaded.append((file.name, result))
                    st.write("✅ Uploaded")
                else:
                    st.write(f"❌ {result}")
                    failed_files.append((file.name, f"Upload failed: {result}"))
            status_box.update(label=f"Uploaded {len(uploaded)}/{len(uploaded_files)} files", state="complete", expanded=False)

        # --- Phase 2: Queue all embed jobs (fast — server returns task_id immediately) ---
        tasks = []   # [(original_name, task_id)]
        for orig_name, server_name in uploaded:
            ok, result = start_embed(server_name)
            if ok:
                tasks.append((orig_name, result))
            else:
                failed_files.append((orig_name, f"Failed to queue embed: {result}"))

        # --- Phase 3: Poll all tasks with live progress display ---
        if tasks:
            progress_placeholder = st.empty()
            task_states = {task_id: {"name": name, "status": "queued"} for name, task_id in tasks}

            while True:
                all_done = True
                for task_id, state in task_states.items():
                    if state["status"] in ("queued", "running"):
                        result = poll_embed_task(task_id)
                        task_states[task_id]["status"] = result.get("status", "failed")
                        if result.get("chunks"):
                            task_states[task_id]["chunks"] = result["chunks"]
                        if result.get("error"):
                            task_states[task_id]["error"] = result["error"]
                    if task_states[task_id]["status"] in ("queued", "running"):
                        all_done = False

                # Build live status display
                lines = []
                for state in task_states.values():
                    s = state["status"]
                    name = state["name"]
                    if s == "complete":
                        lines.append(f"✅ **{name}** — {state.get('chunks', '?')} chunks")
                    elif s == "failed":
                        lines.append(f"❌ **{name}** — {state.get('error', 'Failed')}")
                        if (name, state.get("error", "Embedding failed")) not in [(f, e) for f, e in failed_files]:
                            failed_files.append((name, state.get("error", "Embedding failed")))
                    elif s == "running":
                        lines.append(f"⏳ **{name}** — embedding...")
                    else:
                        lines.append(f"🔵 **{name}** — queued")

                progress_placeholder.markdown("\n\n".join(lines))

                if all_done:
                    break
                time.sleep(3)

        # Refresh file list
        st.session_state.user_uploads = requests.get(
            f"{st.session_state.server_ip}/uploads",
            params={"user_id": "public"}
        ).json().get("files", [])

        st.session_state.upload_failures = failed_files
        return True

    except Exception as e:
        st.session_state.upload_failures = [(None, str(e))]
        st.error(f"Error: {e}", icon="🚫")
        return False


def delete_file_from_server(file_name: str) -> tuple[bool, str]:
    """Delete a file from the server and remove its embeddings."""
    try:
        resp = requests.post(
            f"{server_ip}/delete_file",
            data={"user_id": user_id, "file_name": file_name}
        )
        if resp.status_code == 200:
            return True, resp.json().get("message", "File deleted.")
        else:
            return False, resp.json().get("error", "Unknown error.")
    except Exception as e:
        return False, str(e)


def render_source_doc(doc: dict):
    """Render a source document card: document name, page, content snippet, and open link."""
    metadata = doc.get('metadata', {})
    content = doc.get('page_content', '')

    doc_name = metadata.get('source') or metadata.get('file_path', 'Unknown document')
    page = metadata.get('page')  # 0-indexed for PDFs, None for txt/md

    # Build URL to open the original file in a new tab
    # All files are stored under the shared "public" library
    doc_url = (
        f"{server_ip}/file"
        f"?user_id=public"
        f"&file_name={urllib.parse.quote(doc_name)}"
    )
    if page is not None:
        doc_url += f"#page={page + 1}"  # PDF viewers use 1-indexed page fragments

    # Header: document name + page number + open button
    info_col, btn_col = st.columns([7, 3])
    with info_col:
        if page is not None:
            st.markdown(f"**{doc_name}** — Page {page + 1}")
        else:
            st.markdown(f"**{doc_name}**")
    with btn_col:
        st.link_button("Open ↗", doc_url, use_container_width=True)

    st.divider()

    # Content snippet
    st.markdown(content)

    # Extra metadata as small caption (fields not already shown in the header)
    skip = {'source', 'file_path', 'page', 'user_id'}
    extras = {k: v for k, v in metadata.items() if k not in skip and v}
    if extras:
        st.caption("  ·  ".join(f"{k}: {v}" for k, v in extras.items()))


@st.cache_data(ttl=60 * 10, show_spinner=False)
def get_iframe(file_name: str, num_pages: int = 5) -> tuple[bool, str]:
    """Get the iframe HTML for the PDF file."""
    try:
        response = requests.post(
            f"{st.session_state.server_ip}/iframe",
            json={
                "user_id": "public",  # all files live in the shared public library
                "file_name": file_name,
                "num_pages": num_pages
            },
        )
        if response.status_code == 200:
            return True, response.json().get("iframe", "")
        else:
            return False, response.json().get("error", "Unknown error")
    except requests.RequestException as e:
        # log.error(f"Error getting iframe for {file_name}: {e}")
        return False, str(e)


def add_user_account(name: str, new_user_id: str, password: str) -> tuple[bool, str]:
    """Create a new regular user account via the admin API."""
    try:
        resp = requests.post(
            f"{server_ip}/admin/add_user",
            data={"admin_id": user_id, "name": name, "user_id": new_user_id, "password": password}
        )
        if resp.status_code == 201:
            return True, "User created."
        else:
            return False, resp.json().get("error", "Unknown error.")
    except Exception as e:
        return False, str(e)


def delete_user_account(target_user_id: str) -> tuple[bool, str]:
    """Delete a regular user account via the admin API."""
    try:
        resp = requests.post(
            f"{server_ip}/admin/delete_user",
            data={"admin_id": user_id, "target_user_id": target_user_id}
        )
        if resp.status_code == 200:
            return True, "User deleted."
        else:
            return False, resp.json().get("error", "Unknown error.")
    except Exception as e:
        return False, str(e)


# ------------------------------------------------------------------------------
# Sidebar:
# ------------------------------------------------------------------------------

# User Profile:
with st.sidebar.container(border=True):
    c1, c2, c3 = st.columns([1, 6, 3])
    c1.write("👤")
    c2.write(st.session_state.get("name_of_user", "Error Occurred!"))
    if c3.button("Logout", type="secondary", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# Files Panel:
st.sidebar.subheader("📂 Files")

if user_role == "admin":
    # Admin: full file management controls
    sidebar_uploads = st.sidebar.file_uploader(
        "Upload Documents",
        type=['pdf', 'txt', 'md'],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key=f"file_uploader_{st.session_state.uploader_key}",
    )
    if st.sidebar.button("Upload & Embed", type="primary", disabled=not sidebar_uploads):
        if handle_uploaded_files(sidebar_uploads):
            if not st.session_state.get("upload_failures"):
                st.toast("Files processed successfully!", icon="✅")
            st.session_state.uploader_key += 1
            st.rerun()

    # Show any failures from the previous upload run (persists across rerun)
    if st.session_state.get("upload_failures"):
        for file_name, reason in st.session_state.upload_failures:
            label = file_name if file_name else "Unknown file"
            st.sidebar.error(f"**{label}**: {reason}", icon="🚫")

    st.sidebar.divider()

    if not st.session_state.user_uploads:
        st.sidebar.info("No files in library yet.", icon="ℹ️")
    else:
        for file_name in st.session_state.user_uploads:
            col1, col2 = st.sidebar.columns([8, 2])
            col1.caption(file_name)
            if col2.button("🗑️", key=f"del_{file_name}", help=f"Delete {file_name}"):
                ok, msg = delete_file_from_server(file_name)
                if ok:
                    st.session_state.user_uploads = requests.get(
                        f"{st.session_state.server_ip}/uploads",
                        params={"user_id": "public"}
                    ).json().get("files", [])
                    st.cache_data.clear()
                    st.toast(f"Deleted '{file_name}'", icon="✅")
                    st.rerun()
                else:
                    st.sidebar.error(f"Error: {msg}", icon="🚫")

        # Preview section:
        st.sidebar.divider()
        selected_file = st.sidebar.selectbox(
            label="Preview File",
            index=0,
            options=st.session_state.user_uploads,
        )
        if st.sidebar.button("Show Preview"):
            status, content = get_iframe(selected_file)
            if status:
                st.sidebar.markdown(content, unsafe_allow_html=True)
            else:
                st.sidebar.error(f"Error: **{content}**", icon="🚫")

else:
    # Regular user: read-only view of the shared library
    if not st.session_state.user_uploads:
        st.sidebar.info("No documents in library yet.", icon="ℹ️")
    else:
        for file_name in st.session_state.user_uploads:
            st.sidebar.caption(file_name)

        # Preview section:
        st.sidebar.divider()
        selected_file = st.sidebar.selectbox(
            label="Preview File",
            index=0,
            options=st.session_state.user_uploads,
        )
        if st.sidebar.button("Show Preview"):
            status, content = get_iframe(selected_file)
            if status:
                st.sidebar.markdown(content, unsafe_allow_html=True)
            else:
                st.sidebar.error(f"Error: **{content}**", icon="🚫")

st.sidebar.divider()

# User Management Panel (admin only):
if user_role == "admin":
    with st.sidebar.expander("👥 Users"):
        # Add user form:
        with st.container(border=True):
            st.caption("Add User")
            new_name = st.text_input("Name", key="new_user_name", placeholder="Display name")
            new_uid = st.text_input("User ID", key="new_user_id", placeholder="login_id")
            new_pw = st.text_input("Password", key="new_user_pw", type="password")
            if st.button("Create", key="create_user_btn", type="primary"):
                if not new_name or not new_uid or not new_pw:
                    st.error("Fill all fields.", icon="🚫")
                else:
                    ok, msg = add_user_account(new_name, new_uid, new_pw)
                    if ok:
                        st.toast(f"User '{new_uid}' created.", icon="✅")
                        st.rerun()
                    else:
                        st.error(msg, icon="🚫")

        st.divider()

        # List existing regular users:
        try:
            users_resp = requests.get(
                f"{server_ip}/admin/users",
                params={"admin_id": user_id}
            )
            managed_users = users_resp.json().get("users", []) if users_resp.status_code == 200 else []
        except Exception:
            managed_users = []

        if not managed_users:
            st.caption("No regular users yet.")
        else:
            for u in managed_users:
                u_col, btn_col = st.columns([7, 3])
                u_col.caption(u["name"])
                if btn_col.button("🗑️", key=f"del_user_{u['user_id']}", help=f"Delete {u['user_id']}"):
                    ok, msg = delete_user_account(u["user_id"])
                    if ok:
                        st.toast(f"Deleted user '{u['user_id']}'", icon="✅")
                        st.rerun()
                    else:
                        st.error(msg, icon="🚫")

    st.sidebar.divider()

# Dummy Mode Toggle:
st.sidebar.toggle(label="Dummy Response Mode", value=False, key="dummy_mode",
                  help="Toggle to use dummy responses instead of actual LLM responses.")

# Clear my Chat History:
if st.sidebar.button("Clear My Chat History", type="secondary", icon="💬"):
    resp = requests.post(
        f"{server_ip}/clear_chat_history",
        data={"user_id": user_id}
    )

    if resp.status_code == 200:
        st.session_state.chat_history = [
            Message('assistant', "👋, How may I help you today?")
        ]
        st.session_state.last_retrieved_docs = []
        st.success("Chat history cleared successfully!", icon="✅")
    else:
        st.error(resp.json().get("error", "Failed to clear chat history."), icon="🚫")

# with st.sidebar:
#     st.write(st.session_state)

# ------------------------------------------------------------------------------
# Page content:
# ------------------------------------------------------------------------------

a, b = st.columns([0.65, 9.35], vertical_alignment='bottom', gap='small')
a.image("./assets/model_icon.jpg", use_container_width=True)
b.header(st.secrets.app.site_name, divider='rainbow')


for ind, message in enumerate(st.session_state.chat_history):
    if ind < len(st.session_state.chat_history) - 1:                # all messages except last
        if message.type == 'human':
            write_as_human(message.content, message.filenames)

        elif message.type == 'assistant':
            answer = message.content
            if "<think>" in answer:
                answer = answer[answer.find("</think>") + len("</think>"):]
            write_as_ai(answer)

    else:                                                           # Last message
        if message.type == 'human':                                 # if human, write normally
            write_as_human(message.content)

        elif message.type == 'assistant':                           # if assistant
            # Get the answer, thoughts and docs from the message:
            full = message.content
            thoughts = full[
                full.find("<think>")+8:full.find("</think>")
            ] if "<think>" in full else None
            answer = full[full.find("</think>") + len("</think>"):] if thoughts else full
            documents = st.session_state.last_retrieved_docs if st.session_state.last_retrieved_docs else None

            with st.chat_message(name='assistant', avatar='assistant'):
                with st.container(border=True):
                    # # Thinking:
                    # if thoughts:
                    #     cont_thoughts = st.expander("💭 Thoughts", expanded=True).markdown(thoughts)
                    # # Answer:
                    # st.markdown(answer)
                    # # Documents:
                    # if documents:
                    #     tabs = st.expander("🗃️ Sources", expanded=False).tabs(
                    #         tabs=[f"Document {i+1}" for i in range(len(documents))]
                    #     )
                    #     for i, doc in enumerate(documents):
                    #         with tabs[i]:
                    #             st.subheader(":blue[Content:]")
                    #             st.markdown(doc['page_content'])
                    #             st.divider()
                    #             st.subheader(":blue[Source Details:]")
                    #             st.json(doc['metadata'], expanded=False)

                    # Thinking:
                    if thoughts:
                        # cont_thoughts = c1.expander("💭 Thoughts", expanded=True).markdown(thoughts)
                        cont_thoughts = st.popover(
                            "💭 Thoughts", use_container_width=False).markdown(thoughts)
                    # Answer:
                    st.markdown(answer)
                    # Documents:
                    if documents:
                        tabs = st.expander("🗃️ Sources", expanded=False).tabs(
                            tabs=[f"Source {i+1}" for i in range(len(documents))]
                        )
                        for i, doc in enumerate(documents):
                            with tabs[i]:
                                render_source_doc(doc)


if user_message := st.chat_input(
    placeholder="Ask a question about your uploaded documents...",
    max_chars=1000,
):
    # Create Message object from the user input:
    new_message = Message(type="human", content=user_message)

    # Save it to the chat:
    st.session_state.chat_history.append(new_message)
    # Write it on screen:
    write_as_human(new_message.content)
    # Clear last documents:
    st.session_state.last_retrieved_docs = []

    # Guard: require at least one uploaded file before calling RAG:
    if not st.session_state.user_uploads:
        no_docs_msg = (
            "No documents uploaded yet. Please upload at least one document using the "
            "**Files** panel on the left sidebar, then ask your question."
        )
        write_as_ai(no_docs_msg)
        st.session_state.chat_history.append(Message("assistant", no_docs_msg))
        st.rerun()

    # Get response and write it:
    with st.chat_message(name='assistant', avatar='assistant'):
        with st.spinner("Generating response..."):
            full = ""

            # If dummy mode is enabled, use dummy response:
            if st.session_state.get("dummy_mode", False):
                resp_holder = st.empty()
                response = requests.post(
                    f"{server_ip}/rag",
                    json={
                        "query": new_message.content,
                        "session_id": user_id,
                        "dummy": True
                    },
                    stream=True
                )

                for chunk in response.iter_content(chunk_size=None):
                    if chunk:
                        decoded = chunk.decode("utf-8")
                        decoded = json.loads(decoded)

                        if decoded["type"] == "content":
                            full += decoded["data"]
                        # elif decoded["type"] == "metadata":
                        #     full += f"```json\n{json.dumps(decoded['data'], indent=2)}\n```\n\n\n"
                        # elif decoded["type"] == "context":
                        #     documents.append(decoded['data'])
                        # else:
                        #     st.error(decoded['data'])
                        #     continue

                        resp_holder.markdown(full + "█")

            else:                                           # real RAG response from server
                response = requests.post(
                    f"{server_ip}/rag",
                    json={
                        "query": new_message.content,
                        "session_id": user_id,
                        "dummy": False
                    },
                    stream=True
                )

                documents = []
                resp_holder = st.container(border=True)
                document_holder = resp_holder.empty()
                reply_holder = resp_holder.empty()

                for chunk in response.iter_content(chunk_size=None):
                    if chunk:
                        decoded = chunk.decode("utf-8")
                        decoded = json.loads(decoded)

                        if decoded["type"] == "metadata":
                            # Skip metadata for now
                            continue
                            # full += f"```json\n{json.dumps(decoded['data'], indent=2)}\n```\n\n\n"

                        elif decoded["type"] == "context":
                            documents.append(decoded['data'])

                        elif decoded["type"] == "content":
                            full += decoded["data"]

                        else:
                            st.error(decoded['data'])
                            continue

                        if documents:
                            docs = document_holder.expander("🗃️ Sources", expanded=True)
                            tabs = docs.tabs(
                                tabs=[f"Source {i+1}" for i in range(len(documents))])
                            for i, doc in enumerate(documents):
                                with tabs[i]:
                                    render_source_doc(doc)

                        reply_holder.container(border=True).markdown(full + "█")

                st.session_state.last_retrieved_docs = documents
            st.session_state.chat_history.append(Message("assistant", full))
    st.rerun()
