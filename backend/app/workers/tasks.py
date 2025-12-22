import uuid
from datetime import datetime, timezone
from typing import List, Tuple
from app.services.ai_provider import get_embedder

import os
import httpx
from readability import Document as ReadabilityDocument
from bs4 import BeautifulSoup
import tiktoken
from openai import OpenAI
from sqlalchemy.orm import Session

from app.workers.celery_app import celery
from app.db.session import SessionLocal
from app.models.memory import Artifact, IngestionJob, Document, Chunk, Embedding
import hashlib
import random

from pypdf import PdfReader
import io



def _now_utc():
    return datetime.now(timezone.utc)


def extract_readable_text(html: str) -> Tuple[str, str]:
    """
    Returns (title, text).
    Uses readability-lxml, falls back to soup.get_text.
    """
    try:
        doc = ReadabilityDocument(html)
        title = (doc.short_title() or "").strip()
        summary_html = doc.summary(html_partial=True)
        soup = BeautifulSoup(summary_html, "lxml")
        text = soup.get_text(separator="\n").strip()
        if text:
            return title, text
    except Exception:
        pass

    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string if soup.title and soup.title.string else "").strip()
    text = soup.get_text(separator="\n").strip()
    return title, text


def chunk_text(text: str, max_tokens: int = 800, overlap: int = 100) -> List[str]:
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)
    if not tokens:
        return []

    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(enc.decode(chunk_tokens))
        if end == len(tokens):
            break
        start = max(0, end - overlap)
    return chunks


def embed_texts(client: OpenAI, texts: List[str], model: str) -> Tuple[List[List[float]], int]:
    resp = client.embeddings.create(model=model, input=texts)
    vectors = [d.embedding for d in resp.data]
    dims = len(vectors[0]) if vectors else 0
    return vectors, dims


@celery.task(name="app.workers.tasks.process_url_job", bind=True, max_retries=3)
def process_url_job(self, job_id: str) -> None:
    db: Session = SessionLocal()
    try:
        job_uuid = uuid.UUID(job_id)
        job = db.get(IngestionJob, job_uuid)
        if not job:
            return

        job.status = "RUNNING"
        job.attempts = (job.attempts or 0) + 1
        job.error_message = None
        db.commit()

        artifact = db.get(Artifact, job.artifact_id)
        if not artifact or not artifact.source_uri:
            raise RuntimeError("Artifact missing source_uri")

        url = artifact.source_uri
        with httpx.Client(follow_redirects=True, timeout=15.0, headers={"User-Agent": "TwinMind/1.0"}) as client_http:
            r = client_http.get(url)
            r.raise_for_status()
            html = r.text

        title, text = extract_readable_text(html)
        if not text or len(text.strip()) < 50:
            raise RuntimeError("Failed to extract meaningful text from URL")

        captured_at = artifact.captured_at or _now_utc()

        doc = Document(
            artifact_id=artifact.id,
            user_id=artifact.user_id,
            title=title or url,
            source_type="web",
            source_uri=url,
            captured_at=captured_at,
            meta={"url": url},
        )
        db.add(doc)
        db.flush()

        # chunk
        chunks = chunk_text(text, max_tokens=800, overlap=100)
        if not chunks:
            raise RuntimeError("Chunking produced 0 chunks")

        # embed
        # use_fake = os.getenv("USE_FAKE_EMBEDDINGS") == "1" or not os.getenv("OPENAI_API_KEY")

        # if use_fake:
        #     embed_model = "mock-embedding-v1"
        #     vectors = [fake_embedding(c) for c in chunks]
        #     dims = len(vectors[0])
        # else:
        #     oai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        #     embed_model = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-large")
        #     vectors, dims = embed_texts(oai, chunks, embed_model)
        embedder = get_embedder()

        vectors, dims, model_name = embedder.embed_texts(chunks)


        # store chunks + embeddings
        for i, (chunk_text_i, vec) in enumerate(zip(chunks, vectors)):
            ch = Chunk(
                document_id=doc.id,
                user_id=artifact.user_id,
                chunk_index=i,
                content=chunk_text_i,
                token_count=None,
                char_start=None,
                char_end=None,
                captured_at=captured_at,
                time_start_ms=None,
                time_end_ms=None,
                meta=None,
            )
            db.add(ch)
            db.flush()

            emb = Embedding(
                chunk_id=ch.id,
                user_id=artifact.user_id,
                model=model_name,
                dims=dims,
                embedding=vec,
            )
            db.add(emb)

        job.status = "SUCCEEDED"
        db.commit()

    except Exception as e:
        db.rollback()
        try:
            job_uuid = uuid.UUID(job_id)
            job = db.get(IngestionJob, job_uuid)
            if job:
                job.status = "FAILED"
                job.error_message = str(e)
                db.commit()
        except Exception:
            pass

        msg = str(e).lower()
        transient = any(s in msg for s in ["timeout", "connection", "temporarily unavailable", "rate limit"])

        if transient and self.request.retries < 3:
            raise self.retry(exc=e, countdown=min(60, 2 ** self.request.retries))

        raise
    finally:
        db.close()

@celery.task(name="app.workers.tasks.process_audio_job", bind=True, max_retries=3)
def process_audio_job(self, job_id: str) -> None:
    db: Session = SessionLocal()
    try:
        job_uuid = uuid.UUID(job_id)
        job = db.get(IngestionJob, job_uuid)
        if not job:
            return

        job.status = "RUNNING"
        job.attempts = (job.attempts or 0) + 1
        job.error_message = None
        db.commit()

        artifact = db.get(Artifact, job.artifact_id)
        if not artifact:
            raise RuntimeError("Artifact not found")

        hex_bytes = (artifact.meta or {}).get("bytes")
        if not hex_bytes:
            raise RuntimeError("No audio bytes found on artifact.meta['bytes']")
        audio_bytes = bytes.fromhex(hex_bytes)
        if len(audio_bytes) < 200:
            raise RuntimeError("Audio bytes too small or corrupt")

        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY missing for transcription")

        meta = artifact.meta or {}
        filename = meta.get("filename") or "audio"
        content_type = meta.get("content_type") or ""
        ext = "wav"
        if "." in filename:
            ext = filename.rsplit(".", 1)[1].lower()[:6] or ext
        elif "mpeg" in content_type:
            ext = "mp3"
        elif "m4a" in content_type:
            ext = "m4a"

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        buf = io.BytesIO(audio_bytes)
        buf.name = f"upload.{ext}"
        transcript = client.audio.transcriptions.create(
            model=os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
            file=buf,
        ).text

        if not transcript or len(transcript.strip()) < 5:
            raise RuntimeError("Empty transcript")

        captured_at = artifact.captured_at or _now_utc()

        doc = Document(
            artifact_id=artifact.id,
            user_id=artifact.user_id,
            title=artifact.source_uri or "Audio",
            source_type="audio",
            source_uri=artifact.source_uri,
            captured_at=captured_at,
            meta={"filename": artifact.source_uri},
        )
        db.add(doc)
        db.flush()

        chunks = chunk_text(transcript, max_tokens=500, overlap=80)
        if not chunks:
            raise RuntimeError("Chunking produced 0 chunks")

        embedder = get_embedder()
        vectors, dims, model_name = embedder.embed_texts(chunks)

        for i, (chunk_text_i, vec) in enumerate(zip(chunks, vectors)):
            ch = Chunk(
                document_id=doc.id,
                user_id=artifact.user_id,
                chunk_index=i,
                content=chunk_text_i,
                captured_at=captured_at,
            )
            db.add(ch)
            db.flush()

            db.add(Embedding(
                chunk_id=ch.id,
                user_id=artifact.user_id,
                model=model_name,
                dims=dims,
                embedding=vec,
            ))

        job.status = "SUCCEEDED"
        db.commit()

    except Exception as e:
        db.rollback()
        try:
            job_uuid = uuid.UUID(job_id)
            job = db.get(IngestionJob, job_uuid)
            if job:
                job.status = "FAILED"
                job.error_message = str(e)
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()

@celery.task(name="app.workers.tasks.process_pdf_job", bind=True, max_retries=3)
def process_pdf_job(self, job_id: str) -> None:
    db: Session = SessionLocal()
    try:
        job_uuid = uuid.UUID(job_id)
        job = db.get(IngestionJob, job_uuid)
        if not job:
            return

        job.status = "RUNNING"
        job.attempts = (job.attempts or 0) + 1
        job.error_message = None
        db.commit()

        artifact = db.get(Artifact, job.artifact_id)
        if not artifact:
            raise RuntimeError("Artifact not found")

        hex_bytes = (artifact.meta or {}).get("bytes")
        if not hex_bytes:
            raise RuntimeError("No pdf bytes found on artifact.meta['bytes']")
        pdf_bytes = bytes.fromhex(hex_bytes)

        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages_text = []
        for p in reader.pages:
            t = p.extract_text() or ""
            if t.strip():
                pages_text.append(t)

        full_text = "\n\n".join(pages_text).strip()
        if len(full_text) < 50:
            raise RuntimeError("PDF text extraction produced too little text")

        captured_at = artifact.captured_at or _now_utc()
        title = (artifact.source_uri or "PDF")

        doc = Document(
            artifact_id=artifact.id,
            user_id=artifact.user_id,
            title=title,
            source_type="pdf",
            source_uri=artifact.source_uri,
            captured_at=captured_at,
            meta={"filename": artifact.source_uri},
        )
        db.add(doc)
        db.flush()

        chunks = chunk_text(full_text, max_tokens=700, overlap=120)
        if not chunks:
            raise RuntimeError("Chunking produced 0 chunks")

        embedder = get_embedder()
        vectors, dims, model_name = embedder.embed_texts(chunks)

        for i, (chunk_text_i, vec) in enumerate(zip(chunks, vectors)):
            ch = Chunk(
                document_id=doc.id,
                user_id=artifact.user_id,
                chunk_index=i,
                content=chunk_text_i,
                captured_at=captured_at,
            )
            db.add(ch)
            db.flush()

            db.add(Embedding(
                chunk_id=ch.id,
                user_id=artifact.user_id,
                model=model_name,
                dims=dims,
                embedding=vec,
            ))

        job.status = "SUCCEEDED"
        db.commit()

    except Exception as e:
        db.rollback()
        try:
            job_uuid = uuid.UUID(job_id)
            job = db.get(IngestionJob, job_uuid)
            if job:
                job.status = "FAILED"
                job.error_message = str(e)
                db.commit()
        except Exception:
            pass
        raise
    finally:
        db.close()
