import os
from typing import List, Dict, Any
from openai import OpenAI

def rerank(query: str, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not hits or os.getenv("USE_RERANK") != "1" or not os.getenv("OPENAI_API_KEY"):
        return hits

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.getenv("RERANK_MODEL", os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini"))

    items = []
    for i, h in enumerate(hits, start=1):
        items.append(f"#{i}\nTITLE: {h.get('title','')}\nCONTENT:\n{(h.get('content','') or '')[:1500]}\n")

    prompt = (
        "You are reranking search results for a personal knowledge base.\n"
        "Given a user query and candidate passages, output a JSON array of item numbers "
        "sorted from most relevant to least relevant.\n"
        "Only output JSON.\n\n"
        f"QUERY: {query}\n\n"
        "ITEMS:\n" + "\n---\n".join(items)
    )

    resp = client.responses.create(model=model, input=prompt)
    text = resp.output_text.strip()

    try:
        order = __import__("json").loads(text)
        ordered = []
        seen = set()
        for idx in order:
            if isinstance(idx, int) and 1 <= idx <= len(hits) and idx not in seen:
                ordered.append(hits[idx - 1])
                seen.add(idx)
        # append any missing
        for i in range(1, len(hits)+1):
            if i not in seen:
                ordered.append(hits[i-1])
        return ordered
    except Exception:
        return hits
