## TwinMind Second Brain – Take‑Home Prototype

Foundational “second brain” prototype that ingests web URLs, PDFs, and audio, stores chunked/embedded content in Postgres + pgvector, and answers questions via semantic search + optional LLM rerank + chat synthesis. Built with FastAPI, Celery, Redis, Postgres, and a minimal frontend.

### Repo Map
- `backend/app/main.py` – FastAPI app and routing (chat + ingest).
- `backend/app/api/ingest.py` – URL/PDF/audio ingest endpoints (enqueue Celery jobs).
- `backend/app/workers/tasks.py` – Celery jobs: fetch/scrape URL, extract PDF text, transcribe audio, chunk, embed, persist.
- `backend/app/services/{ai_provider,retrieval,rerank}.py` – Embeddings/LLM providers, vector search, optional rerank.
- `backend/app/models/memory.py` – Artifacts, documents, chunks, embeddings schema (pgvector `vector` without fixed dim).
- `backend/docs/system_design.md` – Full system design per assignment (pipelines, retrieval, schema, scaling, privacy).
- `frontend/app/index.html` – Simple UI for ingest + chat (served by backend `/`).
- `docker-compose.yml` – Postgres + Redis.

### Quick Start
1) **Prereqs:** Python 3.9+, Docker.  
2) **Env:** `cp backend/.env backend/.env.local` (or edit `.env`) and set `OPENAI_API_KEY` (and `OLLAMA_*` if using local embeddings/LLM).  
3) **Services:** From repo root:
   - `docker-compose up -d` (Postgres, Redis)
   - `cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
   - `cd backend && uvicorn app.main:app --reload --port 8000`
   - `cd backend && celery -A app.workers.celery_app.celery worker -Q ingest --loglevel=INFO`
4) **UI:** Open `http://127.0.0.1:8000/`. The frontend is served by FastAPI; keep the backend running.

### Usage
- **Identity:** UI auto-generates a `user_id` and stores it locally. Use “New session” to isolate ingests.
- **Ingest:** In the UI (or via curl):
  - URL: `POST /ingest/url` JSON `{"user_id":"<uuid>","url":"https://example.com"}`
  - PDF: `POST /ingest/pdf` form-data `user_id=<uuid>`, `file=@file.pdf`
  - Audio: `POST /ingest/audio` form-data `user_id=<uuid>`, `file=@audio.m4a`
  - Job status: `GET /ingest/job/{job_id}`
- **Chat:** `POST /chat` JSON `{"user_id":"<uuid>","query":"Summarize my audio in 5 lines"}`. Returns `answer` + `sources`.

### Env Toggles & Behavior
- `EMBEDDING_PROVIDER`: `ollama` (default, nomic-embed-text) or `openai` (text-embedding-3-small). `dims` stored per row; pgvector column is variable-length to avoid mismatch errors.
- `LLM_PROVIDER`: `openai` (default) or `ollama`.
- `USE_RERANK`: `1` enables LLM rerank of top-K vector hits.
- `OPENAI_TRANSCRIBE_MODEL`: defaults to `gpt-4o-mini-transcribe` for audio.
- `USE_FAKE_LLM`: if set, chat returns a fallback snippet without calling the LLM.

### Notes & Trade-offs
- **Embeddings:** Provider pluggable; dimensionality tracked per embedding row, so multiple models can coexist if needed.
- **Rerank:** Optional LLM rerank for precision on small corpora.
- **Temporal:** `captured_at` on artifacts/chunks enables time-aware queries (“last month”, etc.).
- **Privacy:** Per-user scoping; blob bytes are stored in metadata for the prototype (could move to object storage). Local-first is possible with Ollama.

### Tests / Validation
- Smoke test ingest + chat via the curl examples above.
- Check Celery worker logs for job success/failure; `GET /ingest/job/{job_id}` reports status.
- Verify embeddings `dims` match your chosen provider; pgvector column accepts variable length.
- If audio transcription fails, confirm file extension/content-type; worker passes an inferred filename to OpenAI for parsing.

### Deliverables
- **System design:** `backend/docs/system_design.md`
- **Source:** This repo
- **Demo/UI:** Served at `http://127.0.0.1:8000/`
- **Video (optional per assignment):** Record a short walkthrough of architecture + UI/flow.
