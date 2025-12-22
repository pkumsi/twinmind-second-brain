# TwinMind Second Brain – System Design

## 1. Architecture Overview
- **Components:** FastAPI edge (ingest + chat), Postgres + pgvector (artifacts, documents, chunks, embeddings), Celery + Redis (async jobs), AI providers (OpenAI/Ollama), static web UI.
- **Principles:** isolate ingestion from user requests, store rich metadata (source, modality, captured_at), use chunk-level indexing with explicit embedding dims, keep variable-dimension `vector` column to tolerate provider swaps.

## 1.1 Multi-Modal Data Ingestion Pipeline
Common flow: request → Artifact row → IngestionJob row (PENDING) → Celery worker → modality-specific processor → Document + Chunks + Embeddings.

- **Audio (.mp3/.m4a):**
  - Store uploaded bytes on `artifact.metadata.bytes` (hex) with filename/content_type.
  - Worker transcribes via OpenAI Whisper (`gpt-4o-mini-transcribe`), chunks transcript (~500 tokens with 80 overlap), embeds, stores chunk-level embeddings.
  - Timestamps: `captured_at` set at upload (can be overridden later with diarization if available).
- **Documents (.pdf/.md):**
  - PDF: store bytes; worker extracts text per page with PyPDF, concatenates, chunks (~700 tokens with 120 overlap), embeds.
  - Markdown/text (future): parse frontmatter for `title`, `tags`, `captured_at`; reuse same chunker.
- **Web Content (URL):**
  - Fetch with httpx, Readability to strip boilerplate, fallback to BeautifulSoup text; chunk and embed.
- **Plain Text / Notes:**
  - Direct text payload bypasses file storage; chunk + embed synchronously or via small Celery task.
- **Images:**
  - Store original binary in blob storage (local/S3) referenced by `artifact.object_key`, plus thumbnail metadata.
  - Generate captions/alt-text (e.g., BLIP/CLIP) → index caption text as a Document so image becomes searchable via associated text metadata; keep vectors tied to caption, not pixels.

### Sequence (example: /ingest/pdf)
```
POST /ingest/pdf (user_id, UploadFile)
→ create Artifact(type=pdf, metadata: filename/content_type/bytes, captured_at)
→ create IngestionJob(status=PENDING)
→ Celery process_pdf_job
     → extract text → chunk → embed (provider-chosen dims) → insert Document/Chunks/Embeddings
     → update job status SUCCEEDED/FAILED
```

## 1.2 Information Retrieval & Querying Strategy
- **Primary:** Semantic search via pgvector (`embedding <=> query_vector`) with per-user and per-dimension filtering.
- **Rerank:** Optional LLM rerank (`USE_RERANK=1`) over top-K vectors for precision on small corpora.
- **Temporal & Metadata Filters:** push down `captured_at BETWEEN ...` and modality/source filters at SQL level.
- **Justification:** Vector search handles paraphrase + multilingual queries; LLM rerank improves ordering without heavy infra. BM25/keyword can be added later via PostgreSQL `tsvector` for exact match boost if observed need.

## 1.3 Data Indexing & Storage Model
- **Chunking:** token-based sliding window (800 for web, 700 pdf, 500 audio) with overlaps (80–120) to preserve context boundaries; stores `chunk_index` for ordering.
- **Embedding:** Chunks embedded with chosen provider (OpenAI or Ollama). We persist `model` and `dims`; column type is `vector` **without fixed dimension** to tolerate provider swaps. Retrieval filters on `dims` to avoid mixing incompatible vectors.
- **Schema (core fields):**
  - `artifacts(id, user_id, type, source_uri, object_key, captured_at, ingested_at, metadata)`
  - `ingestion_jobs(id, artifact_id, status, attempts, error_message, created_at, updated_at)`
  - `documents(id, artifact_id, user_id, title, source_type, source_uri, captured_at, metadata)`
  - `chunks(id, document_id, user_id, chunk_index, content, captured_at, token_count, time_start_ms, time_end_ms, metadata)`
  - `embeddings(chunk_id, user_id, model, dims, embedding, created_at)`
- **Lifecycle:** Artifact → IngestionJob → Document → Chunk(s) → Embedding(s). Deletes cascade from Artifact downward.
- **Trade-offs:** Postgres + pgvector keeps SQL + vector together (simplicity, transactional writes) and scales to “thousands of docs/user” comfortably. For heavier workloads, vector store offloading (e.g., Qdrant) could reduce DB load but adds infra and consistency complexity.

## 1.4 Temporal Querying Support
- `captured_at` set as close to content creation time as available; defaults to ingestion time.
- Queries can filter by `captured_at` and sort to answer “What did I work on last month?” by combining WHERE + ORDER on `captured_at` and optionally slicing by modality.
- Time-aware rerank: provide timestamps in the LLM prompt so answers can respect recency.

## 1.5 Scalability & Privacy
- **Scale (per-user thousands of docs):** indexes on `user_id`, `captured_at`, and vector `dims`; chunk-level sharding by user; Celery workers horizontal scaling; streaming fetch for large files; keep embedding batch sizes reasonable to avoid rate limits.
- **Privacy by design:** per-user row-level scoping (no cross-user queries); blobs can remain local-first (filesystem) with optional cloud bucket toggle per deployment. API never logs raw content; only metadata and embeddings stored.
- **Cloud vs Local-first:** Cloud eases managed GPUs/LLMs but increases trust/attack surface; local-first uses Ollama for embedding/LLM, keeps binaries on disk, at the cost of compute availability and model freshness.
