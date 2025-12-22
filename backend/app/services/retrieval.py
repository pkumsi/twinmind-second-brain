from sqlalchemy import text
from app.services.ai_provider import get_embedder, vector_to_pgvector_literal

def retrieve_top_chunks(db, user_id: str, query: str, top_k: int = 5):
    embedder = get_embedder()
    qvecs, qdims, _ = embedder.embed_texts([query])
    if not qvecs or not qvecs[0]:
        return []
    qvec_literal = vector_to_pgvector_literal(qvecs[0])

    sql = text("""
        SELECT
          c.id::text AS chunk_id,
          c.content AS content,
          d.title AS title,
          d.source_uri AS source_uri,
          c.captured_at AS captured_at,
          (e.embedding <=> (:qvec)::vector) AS distance
        FROM embeddings e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE e.user_id = :user_id
          AND e.dims = :qdims
        ORDER BY e.embedding <=> (:qvec)::vector
        LIMIT :top_k
    """)

    return db.execute(
        sql, {"qvec": qvec_literal, "user_id": user_id, "qdims": qdims, "top_k": top_k}
    ).mappings().all()
