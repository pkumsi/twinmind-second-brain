# app/services/ai_provider.py
import os
from typing import List, Tuple
import httpx
from openai import OpenAI

def vector_to_pgvector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
class Embedder:
    def embed_texts(self, texts: List[str]) -> Tuple[List[List[float]], int, str]:
        raise NotImplementedError

class LLM:
    def chat(self, prompt: str) -> str:
        raise NotImplementedError

class OllamaEmbedder(Embedder):
    def __init__(self):
        self.base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    def embed_texts(self, texts: List[str]):
        vecs = []
        for t in texts:
            r = httpx.post(f"{self.base}/api/embeddings", json={"model": self.model, "prompt": t}, timeout=60.0)
            r.raise_for_status()
            vecs.append(r.json()["embedding"])
        return vecs, (len(vecs[0]) if vecs else 0), self.model

class OpenAIEmbedder(Embedder):
    def __init__(self):
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

    def embed_texts(self, texts: List[str]):
        resp = self.client.embeddings.create(model=self.model, input=texts)
        vecs = [d.embedding for d in resp.data]
        return vecs, (len(vecs[0]) if vecs else 0), self.model

class OpenAILLM(LLM):
    def __init__(self):
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

    def chat(self, prompt: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return resp.choices[0].message.content.strip()

class OllamaLLM(LLM):
    def __init__(self):
        self.base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_CHAT_MODEL", "llama3.1")

    def chat(self, prompt: str) -> str:
        r = httpx.post(
            f"{self.base}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=120.0,
        )
        r.raise_for_status()
        return r.json().get("response", "")

def get_embedder() -> Embedder:
    # Hybrid default: Ollama embeddings (384) ALWAYS
    provider = os.getenv("EMBEDDING_PROVIDER", "ollama").lower()
    if provider == "openai":
        return OpenAIEmbedder()
    return OllamaEmbedder()

def get_llm() -> LLM:
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider == "ollama":
        return OllamaLLM()
    return OpenAILLM()
