"""OpenAI access for the Smart AI chatbot.

Wrapped behind a small protocol so retrieval, indexing and the chat endpoint
can all be tested without network access or an API key — the tests substitute a
deterministic stub rather than mocking the SDK's internals.
"""

from __future__ import annotations

import logging
from typing import Protocol

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings

logger = logging.getLogger(__name__)


class LlmUnavailable(Exception):
    """The model could not be reached. Callers degrade rather than fail."""


class AiClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def answer(self, question: str, context: str, history: list[dict]) -> str: ...


#: Constrains the assistant to the retrieved FAQ. Spec 4.1 is explicit that the
#: bot is FAQ-only and must not touch customer data, even inside the
#: authenticated portal — so the prompt forbids inventing anything beyond the
#: supplied context, and no customer data is ever placed in that context.
SYSTEM_PROMPT = """You are Smart AI, the assistant for SmartAWARE, a tax, \
accounting and compliance advisory firm.

Answer using ONLY the FAQ extracts provided below. Rules:
- If the extracts do not contain the answer, say you do not have that \
information and suggest contacting SmartAWARE. Never guess.
- Never invent figures, deadlines, prices, or legal or tax advice.
- You have no access to any customer's account, tasks, invoices or documents. \
If asked about those, say you cannot see account information and direct the \
person to their portal or to SmartAWARE.
- Be concise and professional. Use British English.

FAQ extracts:
{context}"""


class OpenAiClient:
    """Live OpenAI client."""

    def __init__(self) -> None:
        if not settings.OPENAI_API_KEY:
            raise LlmUnavailable("OPENAI_API_KEY is not configured.")
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch. Batched because the indexer often has many at once
        and one request per entry would be needlessly slow and expensive."""
        response = self._client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=texts,
            dimensions=settings.OPENAI_EMBEDDING_DIMENSIONS,
        )
        return [item.embedding for item in response.data]

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def answer(self, question: str, context: str, history: list[dict]) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT.format(context=context)}]
        # Recent turns only: the FAQ context is what grounds the answer, and a
        # long history mostly adds cost and room for drift.
        messages.extend(history[-6:])
        messages.append({"role": "user", "content": question})

        response = self._client.chat.completions.create(
            model=settings.OPENAI_CHAT_MODEL,
            messages=messages,  # type: ignore[arg-type]
            temperature=0.2,
            max_tokens=500,
        )
        return (response.choices[0].message.content or "").strip()


_client: AiClient | None = None


def get_client() -> AiClient:
    """The process-wide client. Overridable in tests."""
    global _client
    if _client is None:
        _client = OpenAiClient()
    return _client


def set_client(client: AiClient | None) -> None:
    global _client
    _client = client
