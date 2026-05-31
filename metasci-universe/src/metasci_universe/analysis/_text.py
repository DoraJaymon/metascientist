"""Text processing backends for co-word and topic analysis."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from sklearn.feature_extraction.text import CountVectorizer, ENGLISH_STOP_WORDS


@dataclass
class TextProcessor:
    """Configurable text processor backed by spaCy or scikit-learn."""

    backend: str = "spacy"
    language: str = "en"
    spacy_model: str | None = None
    custom_stopwords: set[str] = field(default_factory=set)
    lemmatize: bool = True

    def __post_init__(self) -> None:
        self.diagnostics: list[str] = []
        self._nlp = None
        self._sklearn_analyzer = None
        self.stopwords = self._load_stopwords()

        if self.backend == "spacy":
            self._nlp = self._load_spacy()
        else:
            self._sklearn_analyzer = CountVectorizer(stop_words="english", token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9\-]{1,}\b").build_analyzer()

    def terms(self, text: str, *, ngram_min: int, ngram_max: int) -> list[str]:
        """Extract normalized terms and n-grams from one document."""
        if not text.strip():
            return []

        if self.backend == "spacy" and self._nlp is not None:
            tokens = self._spacy_tokens(text)
        else:
            tokens = [token.lower() for token in self._sklearn_analyzer(text)] if self._sklearn_analyzer else []
            tokens = [token for token in tokens if token not in self.custom_stopwords]

        return ngrams(tokens, ngram_min=ngram_min, ngram_max=ngram_max)

    def _load_stopwords(self) -> set[str]:
        stopwords = set(ENGLISH_STOP_WORDS)
        stopwords.update(self.custom_stopwords)
        if self.language == "en":
            try:
                from spacy.lang.en.stop_words import STOP_WORDS as SPACY_EN_STOP_WORDS

                stopwords.update(SPACY_EN_STOP_WORDS)
            except Exception:
                pass
        return {item.lower().strip() for item in stopwords if item}

    def _load_spacy(self):
        try:
            import spacy
        except Exception as exc:
            self.diagnostics.append(f"spaCy is unavailable; falling back to scikit-learn tokenization: {exc}")
            self.backend = "sklearn"
            self._sklearn_analyzer = CountVectorizer(stop_words="english", token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9\-]{1,}\b").build_analyzer()
            return None

        if self.spacy_model:
            try:
                return spacy.load(self.spacy_model, disable=["parser", "ner"])
            except Exception as exc:
                self.diagnostics.append(f"spaCy model {self.spacy_model!r} could not be loaded; using blank {self.language!r} pipeline: {exc}")

        try:
            return spacy.blank(self.language)
        except Exception as exc:
            self.diagnostics.append(f"spaCy blank pipeline for {self.language!r} failed; using blank 'en': {exc}")
            return spacy.blank("en")

    def _spacy_tokens(self, text: str) -> list[str]:
        doc = self._nlp(text)
        tokens = []
        for token in doc:
            if token.is_space or token.is_punct or token.like_num or token.like_url or token.like_email:
                continue
            value = token.lemma_ if self.lemmatize and token.lemma_ and token.lemma_ != "-PRON-" else token.text
            value = value.lower().strip("-_")
            if len(value) < 2:
                continue
            if value in self.stopwords or token.is_stop:
                continue
            if not any(character.isalpha() for character in value):
                continue
            tokens.append(value)
        return tokens


def build_text_processor(
    *,
    backend: str,
    language: str,
    spacy_model: str | None,
    stopwords: list[str] | None = None,
    lemmatize: bool = True,
) -> TextProcessor:
    """Build a text processor and normalize custom stopwords."""
    custom_stopwords = {item.lower().strip() for item in (stopwords or []) if item.strip()}
    return TextProcessor(
        backend=backend,
        language=language,
        spacy_model=spacy_model,
        custom_stopwords=custom_stopwords,
        lemmatize=lemmatize,
    )


def ngrams(tokens: list[str], *, ngram_min: int, ngram_max: int) -> list[str]:
    terms: list[str] = []
    for n in range(ngram_min, ngram_max + 1):
        if n <= 0 or len(tokens) < n:
            continue
        terms.extend(" ".join(tokens[index : index + n]) for index in range(0, len(tokens) - n + 1))
    return terms


def edge_rows(edge_counter: Counter[tuple[str, str]], *, top_edges: int, min_edge_weight: int) -> list[dict[str, Any]]:
    rows = []
    for (source, target), weight in edge_counter.most_common():
        if weight < min_edge_weight:
            continue
        rows.append({"source": source, "target": target, "weight": weight})
        if len(rows) >= top_edges:
            break
    return rows


def count_edges(doc_terms: list[list[str]], allowed_terms: set[str]) -> Counter[tuple[str, str]]:
    edge_counter: Counter[tuple[str, str]] = Counter()
    for terms in doc_terms:
        unique_terms = sorted({term for term in terms if term in allowed_terms})
        for left, right in combinations(unique_terms, 2):
            edge_counter[(left, right)] += 1
    return edge_counter
