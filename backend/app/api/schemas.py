from pydantic import BaseModel, HttpUrl
from typing import Optional, List

class IngestUrlRequest(BaseModel):
    user_id: str
    url: HttpUrl
    captured_at: Optional[str] = None

class IngestResponse(BaseModel):
    job_id: str
    artifact_id: str
    status: str

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    error_message: Optional[str] = None
