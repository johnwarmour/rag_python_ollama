"""
config.py - Central configuration for AI System.

This module stores all configurable constants related to:
- LLMs (chat, summarization)
- Embeddings
- Chunking and content limits
- Verification checks
- Dummy response simulator
"""

# Model configuration::
LLM_PROVIDER: str = "ollama"                         # Options: "ollama", "openai", "anthropic", "google"

LLM_CHAT_MODEL_NAME: str = "gemma3:12b"              # Chatting model
# ollama    → "gemma3:latest"
# openai    → "gpt-4o"
# anthropic → "claude-sonnet-4-6"
# google    → "gemini-2.0-flash"
LLM_CHAT_TEMPERATURE: float = 0.1

EMB_MODEL_NAME: str = "bge-m3:latest"                   # Embeddings model

# The max token count which shall be allowed after 'chat_history + input + context'.
# Note: only applies to Ollama (num_ctx). API providers manage context server-side.
MAX_CONTENT_SIZE: int = 14000


# Verification configuration:
#   - Whether to immediately verify the connection to
#   - the LLM models and the Embeddings models after initialization.
#   - Useful specifically for Ollama models, as they can be loaded on GPU or CPU.
VERIFY_LLM_CONNECTION: bool = False
VERIFY_EMB_CONNECTION: bool = False


# Document Chunking properties:
DOC_CHAR_LIMIT: int = 2000                              # Char limit for each doc.
DOC_OVERLAP_NO: int = 200                               # Char limit for chunk overlap.
EMBED_BATCH_SIZE: int = 32                              # Num of chunks to embed per batch.


# Document Retrieval properties:
DOC_TOKEN_SIZE: int = DOC_CHAR_LIMIT // 4               # Appx number of tokens in each doc.
DOCS_NUM_COUNT: int = 3000 // DOC_TOKEN_SIZE            # Max num of docs to retrieve.


# Database:
VECTOR_DB_PERSIST_DIR: str = "user_faiss"            # Path to persist the vector DB.
VECTOR_DB_INDEX_NAME: str = "index.faiss"               # Name of the vector DB file.

# Rate limiting:
# Enable when switching to an external/paid LLM API to control costs.
# Limits apply per user_id on the /rag endpoint.
RATE_LIMIT_ENABLED: bool = False
RATE_LIMIT_REQUESTS_PER_MINUTE: int = 10


# Dummy response mode properties:
TOKENS_PER_SEC: int = 50                                # num of tokens yielded per sec
BATCH_TOKEN_PS: int = 2                                 # num of tokens yielded in each batch
