"""Discriminative-term matching.

Complements the cross-encoder with a hard lexical signal.  ``discriminative_terms`` come
from the query analyzer as ``{term: rarity 1-10}``; rarity is what matters, because in a
pool of same-domain papers the *task* words ("summarization") appear everywhere while a
specific term ("faithfulness") separates the target from its neighbours.

Score is ``1 - prod(1 - w_i)`` over matched terms, with ``w_i = rarity / 10``.  This is a
noisy-OR: each additional match closes some of the remaining gap to 1, so matching two
rare terms beats matching one, but no single term can saturate the score.

Matching uses spaCy lemmas so "metrics" matches "metric".  Without the model it degrades
to whitespace matching, which **silently changes scores** — hence every result reports
which mode ran.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_nlp: Any = None
_nlp_loaded = False


def get_lemmatizer() -> Optional[Any]:
    global _nlp, _nlp_loaded
    if not _nlp_loaded:
        _nlp_loaded = True
        try:
            import spacy

            _nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
        except Exception as exc:  # ImportError or OSError (model absent)
            logger.warning(
                "spaCy en_core_web_sm unavailable (%s); keyword matching falls back to "
                "whitespace tokens, which scores differently. "
                "Install with: python -m spacy download en_core_web_sm",
                exc,
            )
            _nlp = None
    return _nlp


def _tokens(text: str, mode: str) -> set:
    lowered = (text or "").lower()
    if mode == "lemma":
        nlp = get_lemmatizer()
        if nlp is not None:
            return {
                token.lemma_
                for token in nlp(lowered)
                if not token.is_punct and not token.is_space
            }
    return set(re.findall(r"[\w\-]+", lowered))


def lemmatizer_mode(match_mode: str = "lemma") -> str:
    if match_mode != "lemma":
        return "exact"
    return "spacy" if get_lemmatizer() is not None else "fallback"


def score_text(
    text: str, normalised_weights: Dict[str, float], match_mode: str = "lemma"
) -> Tuple[float, List[str]]:
    """Return ``(score, matched_terms)`` for one document."""
    if not text or not normalised_weights:
        return 0.0, []

    lowered = (text or "").lower()
    tokens = _tokens(text, match_mode)

    matched: List[str] = []
    remaining = 1.0
    for term, weight in normalised_weights.items():
        needle = term.lower().strip()
        if not needle:
            continue
        if " " in needle:
            # Multi-word terms are matched on the raw text; lemmatising a phrase and
            # requiring every lemma would be stricter than the original.
            hit = needle in lowered
        else:
            hit = needle in tokens or needle in lowered
        if hit:
            matched.append(term)
            remaining *= 1.0 - weight

    return (1.0 - remaining if matched else 0.0), matched


def score_records(
    records: Sequence[Any],
    terms: Dict[str, int],
    *,
    match_mode: str = "lemma",
    force: bool = False,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Score records against discriminative terms."""
    if not terms:
        return {}, {"scored": 0, "skipped": 0, "lemmatizer": lemmatizer_mode(match_mode),
                    "per_term_hits": {}, "nonzero": 0}

    normalised = {term: min(max(weight / 10.0, 0.0), 1.0) for term, weight in terms.items()}
    hits = {term: 0 for term in terms}
    scores: Dict[str, float] = {}
    skipped = 0

    for record in records:
        if not force and record.keyword_match_score is not None:
            skipped += 1
            continue
        paper_id = record.openalex_id or record.corpus_id
        if not paper_id:
            continue
        text = f"{record.title or ''} {record.abstract or ''}"
        score, matched = score_text(text, normalised, match_mode)
        scores[paper_id] = score
        for term in matched:
            hits[term] += 1

    return scores, {
        "scored": len(scores),
        "skipped": skipped,
        "nonzero": sum(1 for value in scores.values() if value > 0),
        "per_term_hits": hits,
        "lemmatizer": lemmatizer_mode(match_mode),
    }
