import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.schemas import IngestUrlRequest, IngestResponse, JobStatusResponse
from app.db.deps import get_db
from app.models.memory import Artifact, IngestionJob
from app.workers.tasks import process_audio_job, process_pdf_job, process_url_job

router = APIRouter(prefix="/ingest", tags=["ingest"])

def _create_job(db: Session, artifact: Artifact) -> IngestionJob:
    job = IngestionJob(
        artifact_id=artifact.id,
        status="PENDING",
        attempts=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job

@router.post("/url", response_model=IngestResponse)
def ingest_url(payload: IngestUrlRequest, db: Session = Depends(get_db)):
    captured_at = None
    if payload.captured_at:
        try:
            captured_at = datetime.fromisoformat(payload.captured_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="captured_at must be ISO-8601")

    artifact = Artifact(
        user_id=uuid.UUID(payload.user_id),
        type="web",
        source_uri=str(payload.url),
        object_key=None,
        captured_at=captured_at,
        meta={"source": "url"},
    )
    db.add(artifact)
    db.flush()

    job = _create_job(db, artifact)

    process_url_job.delay(str(job.id))
    return IngestResponse(job_id=str(job.id), artifact_id=str(artifact.id), status=job.status)

def _ingest_file(
    db: Session,
    user_id: str,
    file: UploadFile,
    source_type: str,
) -> tuple[Artifact, IngestionJob]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded file is empty")

    artifact = Artifact(
        user_id=uuid.UUID(user_id),
        type=source_type,
        source_uri=file.filename,
        captured_at=datetime.now(timezone.utc),
        meta={
            "filename": file.filename,
            "content_type": file.content_type,
            "bytes": content.hex(),
        },
    )
    db.add(artifact)
    db.flush()

    job = _create_job(db, artifact)
    return artifact, job

@router.post("/pdf", response_model=IngestResponse)
def ingest_pdf(user_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    artifact, job = _ingest_file(db, user_id=user_id, file=file, source_type="pdf")
    process_pdf_job.delay(str(job.id))
    return IngestResponse(job_id=str(job.id), artifact_id=str(artifact.id), status=job.status)

@router.post("/audio", response_model=IngestResponse)
def ingest_audio(user_id: str = Form(...), file: UploadFile = File(...), db: Session = Depends(get_db)):
    artifact, job = _ingest_file(db, user_id=user_id, file=file, source_type="audio")
    process_audio_job.delay(str(job.id))
    return IngestResponse(job_id=str(job.id), artifact_id=str(artifact.id), status=job.status)

@router.get("/job/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(IngestionJob, uuid.UUID(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(job_id=str(job.id), status=job.status, error_message=job.error_message)
