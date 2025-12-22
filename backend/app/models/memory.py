import uuid
from sqlalchemy import (
    Column, String, Text, Integer, DateTime, ForeignKey, JSON, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.db.base import Base

class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    type = Column(String, nullable=False)  # audio|web|pdf|md|note|image
    source_uri = Column(Text, nullable=True)
    object_key = Column(Text, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True, index=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    meta = Column("metadata", JSON, nullable=True)

    jobs = relationship("IngestionJob", back_populates="artifact", cascade="all,delete-orphan")
    documents = relationship("Document", back_populates="artifact", cascade="all,delete-orphan")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="PENDING")  # PENDING|RUNNING|SUCCEEDED|FAILED
    attempts = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    artifact = relationship("Artifact", back_populates="jobs")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(Text, nullable=True)
    source_type = Column(String, nullable=False)
    source_uri = Column(Text, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True, index=True)
    meta = Column("metadata", JSON, nullable=True)

    artifact = relationship("Artifact", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document", cascade="all,delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True, index=True)
    time_start_ms = Column(Integer, nullable=True)
    time_end_ms = Column(Integer, nullable=True)
    meta = Column("metadata", JSON, nullable=True)

    document = relationship("Document", back_populates="chunks")
    embedding = relationship("Embedding", back_populates="chunk", uselist=False, cascade="all,delete-orphan")


class Embedding(Base):
    __tablename__ = "embeddings"

    chunk_id = Column(UUID(as_uuid=True), ForeignKey("chunks.id"), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    model = Column(Text, nullable=False)
    dims = Column(Integer, nullable=False)
    embedding = Column(Vector(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    chunk = relationship("Chunk", back_populates="embedding")
