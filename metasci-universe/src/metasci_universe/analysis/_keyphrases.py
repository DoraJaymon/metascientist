"""Keyphrase extraction helpers for co-word analysis."""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass
class KeyphraseConfig:
    top_n: int = 12
    candidate_limit: int = 80
    embedding_backend: str = "spacy"
    embedding_model: str | None = None
    embedding_api_base_url: str | None = None
    embedding_api_key_env: str | None = "OPENAI_API_KEY"
    merge_llm: bool = False
    merge_model: str | None = None
    merge_api_base_url: str | None = None
    merge_api_key_env: str | None = "OPENAI_API_KEY"
    language: str = "en"
    spacy_model: str | None = None
    stopwords: set[str] | None = None


def extract_keyphrases_for_text(text: str, config: KeyphraseConfig) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract ranked keyphrases from one document using a KeyBERT-style approach."""
    diagnostics: list[str] = []
    if not text.strip():
        return [], diagnostics
    candidates = candidate_phrases(
        text,
        language=config.language,
        spacy_model=config.spacy_model,
        custom_stopwords=config.stopwords or set(),
        limit=config.candidate_limit,
    )
    if not candidates:
        return [], diagnostics
    ranked, rank_diagnostics = rank_keyphrases(text, candidates, config)
    diagnostics.extend(rank_diagnostics)
    return _select_nonredundant_keyphrases(ranked, config.top_n), diagnostics


def extract_keyphrases_for_corpus(
    texts: list[str],
    config: KeyphraseConfig,
    *,
    method: str = "keybert",
) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """Extract keyphrases for a corpus with one implementation boundary."""
    if method == "tfidf_keyphrase":
        return extract_tfidf_keyphrases_for_corpus(texts, config)

    all_rows: list[list[dict[str, Any]]] = []
    diagnostics: list[str] = []
    for text in texts:
        rows, row_diagnostics = extract_keyphrases_for_text(text, config)
        all_rows.append(rows)
        diagnostics.extend(row_diagnostics)
    return all_rows, diagnostics


def extract_tfidf_keyphrases_for_corpus(
    texts: list[str],
    config: KeyphraseConfig,
) -> tuple[list[list[dict[str, Any]]], list[str]]:
    """Extract phrase candidates first, then rank them with corpus-level TF-IDF."""
    diagnostics: list[str] = []
    document_candidates: list[list[str]] = []
    document_evidence: list[dict[str, dict[str, Any]]] = []
    vocabulary: set[str] = set()
    for text in texts:
        evidence = candidate_phrase_evidence(
            text,
            language=config.language,
            spacy_model=config.spacy_model,
            custom_stopwords=config.stopwords or set(),
            limit=config.candidate_limit,
        )
        candidates = list(evidence)
        document_candidates.append(candidates)
        document_evidence.append(evidence)
        vocabulary.update(candidates)

    if not vocabulary:
        return [[] for _ in texts], diagnostics

    try:
        vectorizer = TfidfVectorizer(
            analyzer=lambda tokens: tokens,
            vocabulary=sorted(vocabulary),
            lowercase=False,
            norm=None,
            use_idf=True,
            smooth_idf=True,
            sublinear_tf=True,
        )
        matrix = vectorizer.fit_transform(document_candidates)
        feature_names = np.asarray(vectorizer.get_feature_names_out())
    except Exception as exc:
        return [[] for _ in texts], [f"Corpus TF-IDF keyphrase ranking failed: {exc}"]

    ranked_documents: list[list[dict[str, Any]]] = []
    for row_index, candidates in enumerate(document_candidates):
        if not candidates:
            ranked_documents.append([])
            continue
        row = matrix.getrow(row_index)
        ranked: list[dict[str, Any]] = []
        doc_frequency = np.asarray((matrix > 0).sum(axis=0)).ravel()
        for feature_index, score in zip(row.indices, row.data):
            term = str(feature_names[feature_index])
            evidence = document_evidence[row_index].get(term, {})
            quality = _candidate_prior(term, evidence)
            df = float(doc_frequency[feature_index])
            recurrence = np.log1p(df)
            recurrence_weight = 0.25 if len(term.split()) == 1 else 0.75
            ranked.append(
                {
                    "term": term,
                    "score": round((float(score) * 0.7 + recurrence * recurrence_weight) * quality, 6),
                    "tfidf_score": round(float(score), 6),
                    "quality_score": round(float(quality), 6),
                    "doc_frequency": int(df),
                    "candidate_count": int(evidence.get("count") or 1),
                    "candidate_sources": ";".join(sorted(evidence.get("sources") or [])),
                    "is_proper_noun": bool(evidence.get("is_proper_noun")),
                    "is_noun_chunk": bool(evidence.get("is_noun_chunk")),
                    "is_single_token": bool(evidence.get("is_single_token")),
                    "source": "title_abstract_phrase",
                }
            )
        ranked.sort(
            key=lambda item: (
                item["score"],
                item.get("doc_frequency") or 0,
                item["tfidf_score"],
                -len(str(item["term"]).split()),
                str(item["term"]),
            ),
            reverse=True,
        )
        ranked_documents.append(_select_nonredundant_keyphrases(ranked, config.top_n))
    return ranked_documents, diagnostics


def candidate_phrase_evidence(
    text: str,
    *,
    language: str = "en",
    spacy_model: str | None = None,
    custom_stopwords: set[str] | None = None,
    limit: int = 80,
) -> dict[str, dict[str, Any]]:
    """Generate phrase candidates with evidence about where they came from."""
    custom_stopwords = custom_stopwords or set()
    evidence: dict[str, dict[str, Any]] = {}
    if not spacy_model:
        for span in _candidate_spans(text):
            for candidate in _pattern_candidates_from_tokens(re.findall(r"[A-Za-z][A-Za-z0-9-]*", span)):
                _add_candidate(evidence, candidate, source="pattern", custom_stopwords=custom_stopwords)
    else:
        try:
            nlp = _spacy_nlp(language, spacy_model)
            doc = nlp(text)
            if "parser" in nlp.pipe_names or getattr(doc, "noun_chunks", None):
                try:
                    for chunk in doc.noun_chunks:
                        _add_candidate(evidence, chunk.text, source="noun_chunk", custom_stopwords=custom_stopwords)
                except Exception:
                    pass
            for candidate, source in _proper_noun_candidates(doc):
                _add_candidate(evidence, candidate, source=source, custom_stopwords=custom_stopwords)
            for candidate in _single_token_term_candidates(doc):
                _add_candidate(evidence, candidate, source="single_token", custom_stopwords=custom_stopwords)
            if not evidence:
                for candidate in _pattern_candidates_from_tokens([token.text for token in doc]):
                    _add_candidate(evidence, candidate, source="pattern", custom_stopwords=custom_stopwords)
        except Exception:
            for span in _candidate_spans(text):
                for candidate in _pattern_candidates_from_tokens(re.findall(r"[A-Za-z][A-Za-z0-9-]*", span)):
                    _add_candidate(evidence, candidate, source="pattern", custom_stopwords=custom_stopwords)

    ranked = sorted(evidence.items(), key=lambda item: (item[1]["count"], len(item[0].split()), item[0]), reverse=True)
    return dict(ranked[:limit])


def candidate_phrases(
    text: str,
    *,
    language: str = "en",
    spacy_model: str | None = None,
    custom_stopwords: set[str] | None = None,
    limit: int = 80,
) -> list[str]:
    """Generate noun/terminology phrase candidates without relying on raw n-grams only."""
    return list(
        candidate_phrase_evidence(
            text,
            language=language,
            spacy_model=spacy_model,
            custom_stopwords=custom_stopwords,
            limit=limit,
        )
    )


def _add_candidate(
    evidence: dict[str, dict[str, Any]],
    candidate: str,
    *,
    source: str,
    custom_stopwords: set[str],
) -> None:
    normalized = normalize_keyphrase(candidate)
    if not normalized or _is_weak_phrase(normalized, custom_stopwords):
        return
    row = evidence.setdefault(
        normalized,
        {
            "count": 0,
            "sources": set(),
            "is_proper_noun": False,
            "is_noun_chunk": False,
            "is_single_token": False,
        },
    )
    row["count"] += 1
    row["sources"].add(source)
    row["is_proper_noun"] = row["is_proper_noun"] or source in {"proper_noun", "proper_noun_span"}
    row["is_noun_chunk"] = row["is_noun_chunk"] or source == "noun_chunk"
    row["is_single_token"] = row["is_single_token"] or len(normalized.split()) == 1


def _candidate_spans(text: str) -> list[str]:
    text = re.sub(r"<[^>]+>", " ", text)
    return [span for span in re.split(r"[.!?;:\n\r\t]+", text) if span.strip()]


def _single_token_term_candidates(doc: Any) -> list[str]:
    candidates: list[str] = []
    for token in doc:
        if token.is_space or token.is_punct or token.like_num or token.like_url or token.like_email:
            continue
        if token.is_stop:
            continue
        if token.pos_ not in {"NOUN", "PROPN"}:
            continue
        raw_value = token.lemma_ if token.lemma_ and token.lemma_ != "-PRON-" else token.text
        value = normalize_keyphrase(raw_value)
        if len(value) < 4:
            continue
        candidates.append(value)
    return candidates


def _proper_noun_candidates(doc: Any) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    span: list[str] = []
    for token in doc:
        if token.pos_ == "PROPN" and not token.is_space and not token.is_punct:
            span.append(token.text)
            candidates.append((token.text, "proper_noun"))
            continue
        if span:
            if len(span) > 1:
                candidates.append((" ".join(span), "proper_noun_span"))
            span = []
    if span and len(span) > 1:
        candidates.append((" ".join(span), "proper_noun_span"))
    return candidates


def _pattern_candidates_from_tokens(tokens: list[str]) -> list[str]:
    cleaned = [normalize_keyphrase(token) for token in tokens]
    cleaned = [token for token in cleaned if token]
    candidates: list[str] = []
    stopwords = set(ENGLISH_STOP_WORDS) | _GENERIC_TERM_STOPWORDS | _RHETORICAL_TERM_STOPWORDS
    segments: list[list[str]] = []
    current: list[str] = []
    for token in cleaned:
        if token in stopwords:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)

    for n in (4, 3, 2):
        for segment in segments:
            for index in range(0, len(segment) - n + 1):
                phrase_tokens = segment[index : index + n]
                candidates.append(" ".join(phrase_tokens))
    candidates.extend(
        token
        for segment in segments
        for token in segment
        if token not in stopwords and (len(token) > 3 or token in _MATH_SYMBOL_TOKENS)
    )
    return candidates


def normalize_keyphrase(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.lower()
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\\", " ")
    value = value.replace("/", " ")
    value = re.sub(r"[-‐‑‒–—]+", " ", value)
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _is_weak_phrase(phrase: str, custom_stopwords: set[str]) -> bool:
    tokens = phrase.split()
    if not tokens or len(tokens) > 6:
        return True
    stopwords = set(ENGLISH_STOP_WORDS) | custom_stopwords | _GENERIC_TERM_STOPWORDS
    if all(token in stopwords for token in tokens):
        return True
    if tokens[0] in stopwords or tokens[-1] in stopwords:
        return True
    if any(token in _RHETORICAL_TERM_STOPWORDS for token in tokens):
        return True
    if any(token in ENGLISH_STOP_WORDS for token in tokens):
        return True
    if tokens[0] in _POSSESSIVE_ARTIFACT_TOKENS:
        return True
    if len(tokens) == 2 and any(len(token) == 1 and token not in _MATH_SYMBOL_TOKENS for token in tokens):
        return True
    if len(tokens) == 1 and (len(tokens[0]) < 4 or tokens[0] in stopwords):
        return True
    if any(token in _MATHML_STOPWORDS for token in tokens):
        return True
    if any(token in _FORMULA_ARTIFACT_TOKENS for token in tokens):
        return True
    if len(tokens) == 1 and tokens[0] in _LOW_SIGNAL_SINGLETONS:
        return True
    return False


def _select_nonredundant_keyphrases(rows: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        term = str(row.get("term") or "")
        if not term:
            continue
        term_tokens = term.split()
        if any(_is_nested_phrase(term_tokens, str(existing.get("term") or "").split()) for existing in selected):
            continue
        selected.append(row)
        if len(selected) >= top_n:
            break
    return selected


def _is_nested_phrase(candidate: list[str], existing: list[str]) -> bool:
    if not candidate or not existing or len(candidate) >= len(existing):
        return False
    if len(candidate) == 1 and candidate[0] in _LOW_SIGNAL_SINGLETONS:
        return True
    if len(candidate) == 1:
        return False
    for index in range(0, len(existing) - len(candidate) + 1):
        if existing[index : index + len(candidate)] == candidate:
            return True
    return False


def _phrase_quality(term: str) -> float:
    """Small, domain-agnostic readability prior for TF-IDF phrase ranking."""
    tokens = term.split()
    if not tokens:
        return 0.0
    if len(tokens) == 1:
        return 0.92
    if len(tokens) == 2:
        return 1.0
    if len(tokens) == 3:
        return 0.94
    if len(tokens) == 4:
        return 0.82
    return 0.65


def _candidate_prior(term: str, evidence: dict[str, Any]) -> float:
    prior = _phrase_quality(term)
    if evidence.get("is_noun_chunk"):
        prior *= 1.08
    if evidence.get("is_proper_noun"):
        prior *= 1.22
    if evidence.get("is_single_token") and not evidence.get("is_proper_noun"):
        prior *= 0.72
    count = int(evidence.get("count") or 1)
    if count > 1:
        prior *= 1.0 + min(0.18, np.log1p(count) * 0.05)
    return prior


def rank_keyphrases(
    text: str,
    candidates: list[str],
    config: KeyphraseConfig,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rank candidate phrases by document-candidate embedding similarity."""
    diagnostics: list[str] = []
    docs = [text] + candidates
    vectors, embed_diagnostics = _embed_texts(docs, config)
    diagnostics.extend(embed_diagnostics)
    if vectors is None or len(vectors) != len(docs):
        # Deterministic lexical fallback: useful in dependency-light test environments.
        document_terms = set(normalize_keyphrase(text).split())
        rows = []
        for candidate in candidates:
            tokens = candidate.split()
            overlap = len(set(tokens) & document_terms) / max(1, len(set(tokens)))
            length_bonus = min(0.12, max(0, len(tokens) - 1) * 0.04)
            rows.append({"term": candidate, "score": round(overlap + length_bonus, 6), "source": "title_abstract_phrase"})
        rows.sort(key=lambda row: (row["score"], len(row["term"].split()), row["term"]), reverse=True)
        return rows, diagnostics

    doc_vector = vectors[0]
    candidate_vectors = vectors[1:]
    scores = candidate_vectors @ doc_vector
    rows = []
    for candidate, score in zip(candidates, scores):
        length_bonus = min(0.06, max(0, len(candidate.split()) - 1) * 0.02)
        rows.append(
            {
                "term": candidate,
                "score": round(float(score + length_bonus), 6),
                "source": "title_abstract_phrase",
            }
        )
    rows.sort(key=lambda row: (row["score"], len(row["term"].split()), row["term"]), reverse=True)
    return rows, diagnostics


def _embed_texts(texts: list[str], config: KeyphraseConfig) -> tuple[np.ndarray | None, list[str]]:
    if config.embedding_backend == "sentence_transformers":
        return _embed_sentence_transformers(texts, config)
    if config.embedding_backend == "api":
        return _embed_api_sync(texts, config)
    return _embed_spacy_hash(texts, config)


def _embed_sentence_transformers(texts: list[str], config: KeyphraseConfig) -> tuple[np.ndarray | None, list[str]]:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        return None, [f"sentence-transformers unavailable for keyphrase ranking: {exc}"]
    try:
        model = SentenceTransformer(config.embedding_model or "sentence-transformers/all-MiniLM-L6-v2")
        vectors = model.encode(texts, show_progress_bar=False, convert_to_numpy=True, normalize_embeddings=True)
        return np.asarray(vectors, dtype=np.float32), []
    except Exception as exc:
        return None, [f"SentenceTransformer keyphrase embedding failed: {exc}"]


def _embed_spacy_hash(texts: list[str], config: KeyphraseConfig) -> tuple[np.ndarray | None, list[str]]:
    if not config.embedding_model:
        vectors = np.asarray([_hash_text_vector(text, 384) for text in texts], dtype=np.float32)
        return _normalize_rows(vectors), []
    try:
        nlp = _spacy_nlp(config.language, config.embedding_model)
        if getattr(nlp.vocab, "vectors_length", 0):
            vectors = np.asarray([doc.vector for doc in nlp.pipe(texts)], dtype=np.float32)
        else:
            vectors = np.asarray([_hash_text_vector(text, 384) for text in texts], dtype=np.float32)
        return _normalize_rows(vectors), []
    except Exception as exc:
        return None, [f"spaCy/hash keyphrase embedding failed: {exc}"]


@lru_cache(maxsize=8)
def _spacy_nlp(language: str, model: str | None) -> Any:
    import spacy

    if model:
        return spacy.load(model)
    return spacy.blank(language)


def _embed_api_sync(texts: list[str], config: KeyphraseConfig) -> tuple[np.ndarray | None, list[str]]:
    try:
        import httpx
    except Exception as exc:
        return None, [f"httpx unavailable for keyphrase embedding API: {exc}"]
    api_key = os.environ.get(config.embedding_api_key_env or "OPENAI_API_KEY")
    if not api_key:
        return None, [f"No API key found for keyphrase embedding API in {config.embedding_api_key_env}."]
    base_url = _openai_compatible_base_url(config.embedding_api_base_url)
    model = config.embedding_model or os.environ.get("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
    try:
        response = httpx.post(
            f"{base_url}/embeddings",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": texts},
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload.get("data", []), key=lambda row: row.get("index", 0))
        vectors = np.asarray([row["embedding"] for row in data], dtype=np.float32)
        return _normalize_rows(vectors), []
    except Exception as exc:
        return None, [f"Keyphrase embedding API request failed: {exc}"]


async def merge_keyphrase_aliases_llm(
    terms: list[str],
    *,
    model: str,
    api_base_url: str | None,
    api_key_env: str | None,
) -> tuple[dict[str, str], list[str]]:
    """Use an OpenAI-compatible chat API to merge only clear aliases/abbreviations."""
    diagnostics: list[str] = []
    if not terms:
        return {}, diagnostics
    try:
        import httpx
    except Exception as exc:
        return {}, [f"httpx unavailable for LLM keyphrase merge: {exc}"]
    api_key = os.environ.get(api_key_env or "OPENAI_API_KEY")
    if not api_key:
        return {}, [f"No API key found for LLM keyphrase merge in {api_key_env}."]
    base_url = _openai_compatible_base_url(api_base_url)
    prompt = {
        "task": "Merge only unambiguous aliases, abbreviations, spelling variants, and singular/plural variants.",
        "rules": [
            "Do not merge related but distinct scientific concepts.",
            "Return a JSON object mapping each input term to a canonical term.",
            "If uncertain, map the term to itself.",
        ],
        "terms": terms,
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": "You are a conservative scientific terminology normalizer."},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            payload = _extract_json_object(content)
            mapping = json.loads(payload)
    except Exception as exc:
        return {}, [f"LLM keyphrase merge failed: {exc}"]
    canonical = {}
    term_set = set(terms)
    for term, mapped in mapping.items():
        if term in term_set and isinstance(mapped, str) and mapped.strip():
            canonical[term] = normalize_keyphrase(mapped)
    return canonical, diagnostics


async def refine_keyphrases_for_corpus_llm(
    papers: list[dict[str, Any]],
    candidate_rows: list[list[dict[str, Any]]],
    *,
    model: str,
    api_base_url: str | None,
    api_key_env: str | None,
    target_terms: int = 8,
) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]], list[str]]:
    """Refine per-paper keyphrases with a compact OpenAI-compatible LLM call."""
    diagnostics: list[str] = []
    try:
        import httpx
    except Exception as exc:
        return candidate_rows, [], [f"httpx unavailable for LLM keyphrase refine: {exc}"]
    api_key = os.environ.get(api_key_env or "OPENAI_API_KEY")
    if not api_key:
        return candidate_rows, [], [f"No API key found for LLM keyphrase refine in {api_key_env}."]
    base_url = _openai_compatible_base_url(api_base_url)
    audit_rows: list[dict[str, Any]] = []
    refined_documents: list[list[dict[str, Any]]] = [[] for _ in candidate_rows]
    concurrency = max(1, min(8, int(os.environ.get("KEYPHRASE_LLM_CONCURRENCY", "4"))))
    semaphore = __import__("asyncio").Semaphore(concurrency)
    request_delay = max(0.0, float(os.environ.get("KEYPHRASE_LLM_REQUEST_DELAY", "0")))
    cache_path = _llm_refine_cache_path(model)
    cache = _load_llm_refine_cache(cache_path)
    cache_hits = 0
    cache_misses = 0

    async def refine_one(index: int, paper: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], str | None]:
        nonlocal cache_hits, cache_misses
        if not rows:
            return index, [], [], None
        payload = _llm_refine_payload(paper, rows, target_terms=target_terms)
        cache_key = _llm_refine_cache_key(model=model, payload=payload)
        if cache_key in cache:
            cached = cache[cache_key]
            if cached.get("status") == "ok" and isinstance(cached.get("keywords"), list):
                cache_hits += 1
                refined = [item for item in cached["keywords"] if isinstance(item, dict)]
                return _build_refined_result(index, refined, rows, target_terms)
        cache_misses += 1
        async with semaphore:
            if request_delay:
                await __import__("asyncio").sleep(request_delay)
            refined: list[dict[str, Any]] | None = None
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    response = await client.post(
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "temperature": 0,
                            "messages": [
                                {"role": "system", "content": _LLM_REFINE_SYSTEM_PROMPT},
                                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                            ],
                        },
                    )
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    refined = _parse_llm_refine_response(content)
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < 2:
                        await __import__("asyncio").sleep(_llm_retry_delay(exc, attempt))
            if refined is None:
                error_text = str(last_error) if last_error else "unknown error"
                error = f"LLM keyphrase refine failed for paper_index={index}: {error_text}"
                _append_llm_refine_cache(cache_path, {"cache_key": cache_key, "status": "error", "model": model, "error": error_text})
                return index, rows, [], error
        _append_llm_refine_cache(cache_path, {"cache_key": cache_key, "status": "ok", "model": model, "keywords": refined})
        return _build_refined_result(index, refined, rows, target_terms)

    async with httpx.AsyncClient(timeout=120) as client:
        tasks = [refine_one(index, paper, rows) for index, (paper, rows) in enumerate(zip(papers, candidate_rows))]
        for index, refined_rows, local_audit_rows, diagnostic in await __import__("asyncio").gather(*tasks):
            refined_documents[index] = refined_rows
            audit_rows.extend(local_audit_rows)
            if diagnostic:
                diagnostics.append(diagnostic)
    diagnostics.append(
        f"LLM keyphrase refine cache: path={cache_path}, hits={cache_hits}, misses={cache_misses}."
    )
    return refined_documents, audit_rows, diagnostics


def _build_refined_result(
    index: int,
    refined: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    target_terms: int,
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], None]:
    rows_by_term = {str(row.get("term") or ""): row for row in rows}
    refined_rows: list[dict[str, Any]] = []
    local_audit_rows: list[dict[str, Any]] = []
    for rank, item in enumerate(refined[:target_terms], start=1):
        term = normalize_keyphrase(str(item.get("term") or ""))
        if not term:
            continue
        source_terms = [normalize_keyphrase(str(value)) for value in item.get("source_terms", []) if str(value).strip()]
        source_terms = [value for value in source_terms if value]
        source_row = _match_source_row(term, source_terms, rows, rows_by_term)
        refined_row = {
            **source_row,
            "term": term,
            "raw_term": term,
            "score": source_row.get("score"),
            "source": "llm_refined_keyphrase",
            "llm_category": _normalize_llm_category(str(item.get("category") or "")),
            "llm_source_terms": ";".join(source_terms),
            "llm_rank": rank,
        }
        refined_rows.append(refined_row)
        local_audit_rows.append(
            {
                "paper_index": index,
                "term": term,
                "category": refined_row["llm_category"],
                "source_terms": ";".join(source_terms),
                "rank": rank,
            }
        )
    return index, refined_rows or rows, local_audit_rows, None


def _llm_retry_delay(exc: Exception, attempt: int) -> float:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 429:
        retry_after = getattr(response, "headers", {}).get("retry-after") if response is not None else None
        if retry_after:
            try:
                return max(1.0, float(retry_after))
            except ValueError:
                pass
        base_delay = float(os.environ.get("KEYPHRASE_LLM_RATE_LIMIT_DELAY", "30"))
        return base_delay * (attempt + 1)
    return 1.5 * (attempt + 1)


def _llm_refine_cache_path(model: str) -> Path:
    configured = os.environ.get("KEYPHRASE_LLM_CACHE")
    if configured:
        return Path(configured).expanduser()
    safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "-", model).strip("-") or "model"
    return Path("analysis_output/keyphrase_llm_cache") / f"llm_refine_{safe_model}.jsonl"


def _load_llm_refine_cache(path: Path) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return cache
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = row.get("cache_key")
                if isinstance(key, str):
                    if cache.get(key, {}).get("status") == "ok":
                        continue
                    cache[key] = row
    except OSError:
        return cache
    return cache


def _append_llm_refine_cache(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _llm_refine_cache_key(*, model: str, payload: dict[str, Any]) -> str:
    stable = {
        "model": model,
        "prompt": _LLM_REFINE_SYSTEM_PROMPT,
        "payload": payload,
    }
    return hashlib.sha1(json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _match_source_row(
    term: str,
    source_terms: list[str],
    rows: list[dict[str, Any]],
    rows_by_term: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    for source in [term, *source_terms]:
        if source in rows_by_term:
            return rows_by_term[source]
    for source in source_terms:
        source_tokens = set(source.split())
        if not source_tokens:
            continue
        for row in rows:
            row_term = str(row.get("term") or "")
            row_tokens = set(row_term.split())
            if source in row_term or row_term in source or source_tokens <= row_tokens or row_tokens <= source_tokens:
                return row
    return {}


def _llm_refine_payload(paper: dict[str, Any], rows: list[dict[str, Any]], *, target_terms: int) -> dict[str, Any]:
    return {
        "title": str(paper.get("title") or "")[:500],
        "abstract": str(paper.get("abstract") or "")[:2400],
        "target_terms": target_terms,
        "suggested_categories": [
            "research_object",
            "research_problem",
            "method",
            "resource",
            "field",
            "indicator",
            "other",
        ],
        "candidates": [
            {
                "term": row.get("term"),
                "score": row.get("score"),
                "df": row.get("doc_frequency"),
                "src": row.get("candidate_sources"),
                "proper": row.get("is_proper_noun"),
                "chunk": row.get("is_noun_chunk"),
                "single": row.get("is_single_token"),
            }
            for row in rows[:30]
        ],
    }


def _parse_llm_refine_response(content: str) -> list[dict[str, Any]]:
    payload = json.loads(_extract_json_array_or_object(content))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        keywords = payload.get("keywords")
        if isinstance(keywords, list):
            return [item for item in keywords if isinstance(item, dict)]
    return []


def _extract_json_array_or_object(content: str) -> str:
    content = content.strip()
    array_start = content.find("[")
    object_start = content.find("{")
    starts = [index for index in (array_start, object_start) if index != -1]
    if not starts:
        raise ValueError("No JSON array or object found in LLM response")
    start = min(starts)
    end_char = "]" if content[start] == "[" else "}"
    end = content.rfind(end_char)
    if end < start:
        raise ValueError("Incomplete JSON payload in LLM response")
    return content[start : end + 1]


def _normalize_llm_category(value: str) -> str:
    value = re.sub(r"[^a-z0-9_ -]+", "", value.strip().lower()).replace(" ", "_").replace("-", "_")
    value = re.sub(r"_+", "_", value).strip("_")
    aliases = {
        "object": "research_object",
        "topic": "research_problem",
        "problem": "research_problem",
        "task": "research_problem",
        "database": "resource",
        "dataset": "resource",
        "platform": "resource",
        "tool": "resource",
        "corpus": "resource",
        "software": "resource",
        "metric": "indicator",
        "measure": "indicator",
        "attribute": "research_problem",
        "policy_issue": "research_problem",
        "document_type": "research_object",
        "publication_type": "research_object",
        "geographic_unit": "research_object",
    }
    value = aliases.get(value, value)
    allowed = {"research_object", "research_problem", "method", "resource", "field", "indicator", "other"}
    return value if value in allowed else "other"


_LLM_REFINE_SYSTEM_PROMPT = """You are a conservative academic keyword refiner for bibliometric analysis.
Return only a JSON array. Each item must have exactly: term, category, source_terms.
Pick 5-8 concise keywords from the candidate evidence and paper text.
Use exactly one of these categories:
- research_object: entity, phenomenon, document type, population, or unit being studied
- research_problem: research question, task, comparison, policy issue, concern, or analyzed dimension
- method: method, model, algorithm, analytical approach, or study design
- resource: database, dataset, platform, tool, corpus, or software
- field: discipline, research area, or application domain
- indicator: metric, measure, evaluation criterion, or quantitative indicator
- other: only if none of the above fits
Do not force category balance. A paper may have no method, resource, or indicator keyword.
Prefer core research objects, resources/data sources, methods, named entities, and fields.
Include indicator/metric keywords only when they are central.
Keep important single-token named entities or research objects.
Merge aliases, spelling variants, singular/plural variants, and abbreviations.
You may normalize a candidate to a shorter core term if directly supported by candidates/text.
Do not invent unsupported broad themes. Remove vague phrases and sentence fragments."""


def _openai_compatible_base_url(base_url: str | None) -> str:
    value = (
        base_url
        or os.environ.get("OPENAI_API_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or os.environ.get("API_BASE")
        or "https://api.openai.com/v1"
    )
    return value.rstrip("/")


def _extract_json_object(content: str) -> str:
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in LLM response")
    return content[start : end + 1]


def _hash_text_vector(text: str, dimensions: int) -> np.ndarray:
    vector = np.zeros(dimensions, dtype=np.float32)
    tokens = normalize_keyphrase(text).split()
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return vector


def _normalize_rows(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


_GENERIC_TERM_STOPWORDS = {
    "analysis",
    "approach",
    "article",
    "data",
    "effect",
    "example",
    "method",
    "model",
    "paper",
    "problem",
    "proof",
    "research",
    "result",
    "study",
}

_RHETORICAL_TERM_STOPWORDS = {
    "answer",
    "answers",
    "application",
    "applications",
    "case",
    "cases",
    "certain",
    "construct",
    "construction",
    "existence",
    "extend",
    "extension",
    "general",
    "give",
    "gives",
    "new",
    "note",
    "obtain",
    "paper",
    "present",
    "prove",
    "proved",
    "proves",
    "proving",
    "question",
    "questions",
    "related",
    "remark",
    "remarks",
    "similar",
    "show",
    "showing",
    "shows",
    "theorem",
    "theorems",
    "version",
    "we",
}

_MATH_SYMBOL_TOKENS = {"c", "g", "h", "k", "l", "n", "p", "q", "r", "x"}

_POSSESSIVE_ARTIFACT_TOKENS = {"s"}

_FORMULA_ARTIFACT_TOKENS = {
    "mathbf",
    "mathbb",
    "mathrm",
    "operatorname",
    "text",
}

_LOW_SIGNAL_SINGLETONS = {
    "absolute",
    "conjecture",
    "curves",
    "function",
    "functions",
    "groups",
    "random",
    "space",
    "special",
    "stable",
    "times",
    "universal",
    "varieties",
}

_MATHML_STOPWORDS = {
    "annotation",
    "display",
    "inline",
    "math",
    "mathjax",
    "mathml",
    "mfrac",
    "mi",
    "mml",
    "mn",
    "mo",
    "mrow",
    "msqrt",
    "msub",
    "msubsup",
    "msup",
    "semantics",
    "xmlns",
}
