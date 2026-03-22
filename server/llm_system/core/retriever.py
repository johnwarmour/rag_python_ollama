"""Multi-query retriever that generates query variations to improve retrieval coverage.

Instead of a single embedding of the user's question, this generates N rephrasings,
retrieves for each, then deduplicates — catching chunks that rank highly for one
phrasing but not another.
"""

import asyncio
from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable, RunnableConfig

from logger import get_logger
log = get_logger(name="core_retriever")


_MULTI_QUERY_PROMPT = PromptTemplate.from_template(
    "You are a search query generator.\n"
    "Rephrase the following question into {n} distinct search queries that could find "
    "relevant information from different angles.\n"
    "Output ONLY the queries, one per line, with no numbering, labels, or extra text.\n\n"
    "Question: {question}"
)


class MultiQueryRetriever(Runnable):
    """Wraps a configurable retriever, running multiple query variations per request.

    Generates `n_queries` rephrasings of the input via an LLM, retrieves for each
    (plus the original), deduplicates by content, and returns the merged set.
    Config (including user-id filter in search_kwargs) is forwarded to every
    sub-retriever call so per-user filtering is preserved.
    """

    def __init__(self, retriever: Runnable, llm: BaseChatModel, n_queries: int = 2):
        self.retriever = retriever
        self.llm = llm
        self.n_queries = n_queries
        self._chain = _MULTI_QUERY_PROMPT | llm

    def _parse(self, llm_output: str) -> List[str]:
        lines = llm_output.strip().split("\n")
        return [q.strip() for q in lines if q.strip()][: self.n_queries]

    def _deduplicate(self, docs: List[Document]) -> List[Document]:
        seen: set = set()
        unique: List[Document] = []
        for doc in docs:
            key = hash(doc.page_content)
            if key not in seen:
                seen.add(key)
                unique.append(doc)
        return unique

    def invoke(self, input: str, config: Optional[RunnableConfig] = None) -> List[Document]:
        result = self._chain.invoke({"question": input, "n": self.n_queries})
        queries = self._parse(result.content)
        queries.append(input)

        log.info(f"[MultiQueryRetriever] Generated queries:\n" + "\n".join(f"  {i+1}. {q}" for i, q in enumerate(queries)))
        all_docs: List[Document] = []
        for query in queries:
            all_docs.extend(self.retriever.invoke(query, config=config))

        unique = self._deduplicate(all_docs)
        log.info(f"[MultiQueryRetriever] {len(all_docs)} total → {len(unique)} unique docs after dedup.")
        return unique

    async def ainvoke(self, input: str, config: Optional[RunnableConfig] = None, **kwargs) -> List[Document]:
        result = await self._chain.ainvoke({"question": input, "n": self.n_queries})
        queries = self._parse(result.content)
        queries.append(input)

        log.info(f"[MultiQueryRetriever] Generated queries (async):\n" + "\n".join(f"  {i+1}. {q}" for i, q in enumerate(queries)))
        results = await asyncio.gather(*[
            self.retriever.ainvoke(q, config=config) for q in queries
        ])

        all_docs = [doc for docs in results for doc in docs]
        unique = self._deduplicate(all_docs)
        log.info(f"[MultiQueryRetriever] {len(all_docs)} total → {len(unique)} unique docs after dedup.")
        return unique
