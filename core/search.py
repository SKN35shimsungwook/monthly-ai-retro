"""로컬 검색 인덱스 (RAG의 R).

한국어 형태소 분석기 없이도 잘 맞도록 글자 2~4개 단위 TF-IDF를 쓴다.
검색은 전부 이 PC 안에서 하고, 찾은 몇 개의 메시지만 LLM에 보낸다.
"""
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from core import store

def index_path() -> Path:
    return store.DB_PATH.parent / "index.pkl"


@dataclass
class Hit:
    id: int
    doc: str          # 근거 ID (예: C-120)
    source: str
    ts: str
    title: str
    text: str
    score: float


def build(path: Path | None = None) -> int:
    path = path or index_path()
    rows = store.messages(role=store.EVIDENCE_ROLES)
    if not rows:
        return 0
    corpus = [f"{r['title']} {r['text'][:2000]}" for r in rows]
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1, max_features=200_000, sublinear_tf=True)
    matrix = vec.fit_transform(corpus)
    meta = [{k: r[k] for k in ("id", "source", "ts", "title", "text", "role")} for r in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump({"vec": vec, "matrix": matrix, "meta": meta}, fh)
    return len(rows)


_cache: dict = {}


def _load(path: Path | None = None) -> dict | None:
    path = path or index_path()
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    if _cache.get("mtime") != mtime or _cache.get("path") != path:
        with open(path, "rb") as fh:
            _cache.update(pickle.load(fh), mtime=mtime, path=path)
    return _cache


def search(query: str, k: int = 12, since: str | None = None, until: str | None = None,
           sources: list[str] | None = None, path: Path | None = None) -> list[Hit]:
    idx = _load(path)
    if not idx or not query.strip():
        return []
    meta = idx["meta"]
    mask = np.ones(len(meta), dtype=bool)
    for i, m in enumerate(meta):
        if m.get("role") == "self_report":  # 각 AI의 자기 보고서는 기간과 상관없이 참고
            if sources and m["source"] not in sources:
                mask[i] = False
            continue
        if (since and m["ts"] < since) or (until and m["ts"][:10] > until) or (sources and m["source"] not in sources):
            mask[i] = False
    if not mask.any():
        return []
    scores = (idx["matrix"] @ idx["vec"].transform([query]).T).toarray().ravel()
    scores[~mask] = -1
    order = np.argsort(-scores)[:k]
    hits = []
    for i in order:
        if scores[i] <= 0:
            break
        m = meta[i]
        hits.append(Hit(m["id"], store.doc_id(m["source"], m["id"]), m["source"], m["ts"], m["title"],
                        m["text"], float(scores[i])))
    return hits
