from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

import os
from openai import OpenAI

from app.db.session import get_db
from app.services.retrieval import retrieve_top_chunks
from app.services.rerank import rerank


router = APIRouter()

class ChatRequest(BaseModel):
    user_id: str
    query: str
    top_k: int = 8

class ChatResponse(BaseModel):
    answer: str
    sources: list

def _format_context(hits: list) -> str:
    parts = []
    for i, h in enumerate(hits, start=1):
        title = h.get("title") or ""
        uri = h.get("source_uri") or ""
        captured = h.get("captured_at") or ""
        content = (h.get("content") or "").strip()
        parts.append(
            f"[{i}] Title: {title}\n"
            f"URL: {uri}\n"
            f"CapturedAt: {captured}\n"
            f"Content:\n{content}\n"
        )
    return "\n---\n".join(parts)

def _fallback_answer(query: str, hits: list) -> str:
    if not hits:
        return "I don’t have any saved information yet to answer that."
    top = hits[0]
    return (
        "I couldn’t use the LLM right now, but here’s the most relevant saved snippet:\n\n"
        f"From: {top.get('title') or 'Untitled'}\n"
        f"{top.get('content') or ''}"
    )

@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    hits = retrieve_top_chunks(db=db, user_id=req.user_id, query=req.query, top_k=req.top_k)
    hits = [dict(h) for h in hits]
    hits = rerank(req.query, hits)
    if not hits:
        return {"answer": "No saved content found for this user yet.", "sources": []}

    use_fake_llm = (os.getenv("USE_FAKE_LLM") == "1") or (not os.getenv("OPENAI_API_KEY"))

    if use_fake_llm:
        return {"answer": _fallback_answer(req.query, hits), "sources": hits}

    model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")
    context = _format_context(hits)

    system = (
        "You are a personal 'second brain' assistant.\n"
        "Answer using ONLY the provided context.\n"
        "If the context is insufficient, say what’s missing.\n"
        "When you use facts from a source, cite it like [1], [2].\n"
        "Be concise and helpful."
    )

    user = (
        f"User question: {req.query}\n\n"
        f"Context:\n{context}\n\n"
        "Write a synthesized answer now."
    )

    try:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        answer = resp.choices[0].message.content.strip()
        return {"answer": answer, "sources": hits}

    except Exception as e:
        return {
            "answer": _fallback_answer(req.query, hits) + f"\n\n(LLM unavailable: {e})",
            "sources": hits,
        }
