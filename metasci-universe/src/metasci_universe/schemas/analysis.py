"""Request schemas for analysis tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TextField = Literal["title", "abstract", "topics"]
TextBackend = Literal["spacy", "sklearn"]
TermExtractionMode = Literal["ngram", "keybert", "tfidf_keyphrase"]
TermEmbeddingBackend = Literal["spacy", "sentence_transformers", "api"]
TopicLandscapeMethod = Literal["openalex_topics", "coword", "topic_modeling"]
TopicModelingBackend = Literal["sklearn_lda", "embedding_kmeans", "embedding_hdbscan", "bertopic"]
MacroDimension = Literal["countries", "institutions", "country_collaboration", "institution_collaboration"]
CountingMode = Literal["full", "fractional"]
AuthorLandscapeFocus = Literal["authors", "roles", "collaboration", "affiliations", "topics"]
AnalysisIntent = Literal[
    "auto",
    "bibliometrics",
    "macro",
    "author_landscape",
    "coword",
    "topic_modeling",
    "topic_landscape",
    "citation_overview",
    "science_landscape",
]
ScienceLandscapeComponent = Literal["bibliometrics", "macro", "author_landscape", "topic_landscape", "citation_overview"]


class DatasetAnalysisRequest(BaseModel):
    """Base request for tools that analyze a saved works dataset."""

    model_config = ConfigDict(extra="forbid")

    dataset_path: str = Field(description="Path to a saved MetaSci works dataset file or dataset directory.")
    output_dir: str | None = Field(default=None, description="Directory for analysis artifacts.")


class AnalysisReadinessRequest(DatasetAnalysisRequest):
    """Inspect whether a saved works dataset has enough fields for analysis tools."""


class AnalysisRecommendationRequest(DatasetAnalysisRequest):
    """Recommend analysis tools and safe defaults for a saved works dataset."""

    intent: AnalysisIntent = "auto"


class BibliometricsRequest(DatasetAnalysisRequest):
    """Descriptive bibliometric summary for a works dataset."""

    top_authors: int = Field(default=20, gt=0, le=500)
    top_papers: int = Field(default=20, gt=0, le=500)
    top_sources: int = Field(default=20, gt=0, le=500)
    top_topics: int = Field(default=30, gt=0, le=500)


class MacroAnalysisRequest(DatasetAnalysisRequest):
    """Country, institution, and collaboration-level macro analysis."""

    dimensions: list[MacroDimension] = Field(
        default_factory=lambda: ["countries", "institutions", "country_collaboration", "institution_collaboration"]
    )
    top_n: int = Field(default=30, gt=0, le=500)
    min_count: float = Field(default=1, ge=0)
    counting: CountingMode = "full"
    include_temporal: bool = True
    year_field: str = "publication_year"

    @field_validator("dimensions")
    @classmethod
    def deduplicate_dimensions(cls, value: list[MacroDimension]) -> list[MacroDimension]:
        return sorted(set(value))


class AuthorLandscapeRequest(DatasetAnalysisRequest):
    """Corpus-level author productivity, role, collaboration, and topic analysis."""

    top_n: int = Field(default=30, gt=0, le=500)
    min_papers: int = Field(default=1, ge=1)
    include_temporal: bool = True
    year_field: str = "publication_year"
    focus: list[AuthorLandscapeFocus] = Field(
        default_factory=lambda: ["authors", "roles", "collaboration", "affiliations", "topics"]
    )

    @field_validator("focus")
    @classmethod
    def deduplicate_focus(cls, value: list[AuthorLandscapeFocus]) -> list[AuthorLandscapeFocus]:
        return sorted(set(value))


class CoWordAnalysisRequest(DatasetAnalysisRequest):
    """Co-word and term co-occurrence analysis from titles, abstracts, or topics."""

    text_fields: list[TextField] = Field(default_factory=lambda: ["title", "abstract"])
    text_backend: TextBackend = "sklearn"
    language: str = "en"
    spacy_model: str | None = None
    lemmatize: bool = True
    ngram_min: int = Field(default=1, ge=1, le=5)
    ngram_max: int = Field(default=2, ge=1, le=5)
    min_term_count: int = Field(default=3, ge=1)
    min_edge_weight: int = Field(default=2, ge=1)
    top_terms: int = Field(default=100, gt=0, le=2000)
    top_edges: int = Field(default=300, gt=0, le=10000)
    stopwords: list[str] = Field(default_factory=list)
    term_extraction: TermExtractionMode = Field(default="ngram")
    keyphrase_top_n: int = Field(default=12, gt=0, le=100)
    keyphrase_candidate_limit: int = Field(default=80, gt=0, le=1000)
    keyphrase_embedding_backend: TermEmbeddingBackend = Field(default="spacy")
    keyphrase_embedding_model: str | None = Field(default=None)
    keyphrase_embedding_api_base_url: str | None = Field(default=None)
    keyphrase_embedding_api_key_env: str | None = Field(default="OPENAI_API_KEY")
    keyphrase_merge_llm: bool = Field(default=False)
    keyphrase_merge_model: str | None = Field(default=None)
    keyphrase_merge_api_base_url: str | None = Field(default=None)
    keyphrase_merge_api_key_env: str | None = Field(default="OPENAI_API_KEY")
    selected_terms: list[str] | None = Field(
        default=None,
        description="Optional terms to track in evolution outputs even when they are not top-frequency terms.",
    )
    include_evolution: bool = True
    year_field: str = "publication_year"

    @field_validator("text_fields")
    @classmethod
    def deduplicate_text_fields(cls, value: list[TextField]) -> list[TextField]:
        return sorted(set(value))

    @field_validator("stopwords")
    @classmethod
    def normalize_stopwords(cls, value: list[str]) -> list[str]:
        return sorted({item.lower().strip() for item in value if item.strip()})

    @field_validator("selected_terms")
    @classmethod
    def normalize_selected_terms(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return sorted({item.lower().strip() for item in value if item.strip()})

    @model_validator(mode="after")
    def validate_ngrams(self) -> "CoWordAnalysisRequest":
        if self.ngram_min > self.ngram_max:
            raise ValueError("ngram_min cannot be greater than ngram_max")
        return self


class TopicModelingRequest(DatasetAnalysisRequest):
    """Topic modeling with LDA or BERTopic backends."""

    backend: TopicModelingBackend = "sklearn_lda"
    text_fields: list[TextField] = Field(default_factory=lambda: ["title", "abstract"])
    text_backend: TextBackend = "sklearn"
    language: str = "en"
    spacy_model: str | None = None
    lemmatize: bool = True
    nr_topics: int | None = Field(default=None, ge=2, le=200)
    min_topic_size: int = Field(default=10, ge=2)
    max_docs: int | None = Field(default=None, gt=0)
    max_features: int = Field(default=5000, gt=100, le=100000)
    include_evolution: bool = True
    year_field: str = "publication_year"
    embedding_model: str | None = None
    embedding_artifact: str | None = Field(
        default=None,
        description="Optional embeddings artifact directory, metadata.json, or embeddings.npy to reuse for embedding backends.",
    )
    random_state: int = 42

    @field_validator("text_fields")
    @classmethod
    def deduplicate_text_fields(cls, value: list[TextField]) -> list[TextField]:
        return sorted(set(value))


class TopicLandscapeRequest(DatasetAnalysisRequest):
    """Combined topic landscape analysis across OpenAlex topics, co-word analysis, and topic modeling."""

    methods: list[TopicLandscapeMethod] = Field(
        default_factory=lambda: ["openalex_topics", "coword", "topic_modeling"]
    )
    top_n: int = Field(default=30, gt=0, le=500)
    min_count: int = Field(default=2, ge=1)
    include_evolution: bool = True
    year_field: str = "publication_year"
    text_fields: list[TextField] = Field(default_factory=lambda: ["title", "abstract"])
    text_backend: TextBackend = "sklearn"
    language: str = "en"
    spacy_model: str | None = None
    lemmatize: bool = True
    ngram_min: int = Field(default=1, ge=1, le=5)
    ngram_max: int = Field(default=2, ge=1, le=5)
    selected_topics: list[str] | None = Field(
        default=None,
        description="Optional OpenAlex topic IDs or names to track in topic evolution outputs.",
    )
    selected_terms: list[str] | None = Field(
        default=None,
        description="Optional co-word terms to track in term evolution outputs.",
    )
    modeling_backend: TopicModelingBackend = "sklearn_lda"
    nr_topics: int | None = Field(default=None, ge=2, le=200)
    max_docs: int | None = Field(default=None, gt=0)
    max_features: int = Field(default=5000, gt=100, le=100000)

    @field_validator("methods")
    @classmethod
    def deduplicate_methods(cls, value: list[TopicLandscapeMethod]) -> list[TopicLandscapeMethod]:
        return sorted(set(value))

    @field_validator("text_fields")
    @classmethod
    def deduplicate_text_fields(cls, value: list[TextField]) -> list[TextField]:
        return sorted(set(value))

    @field_validator("selected_topics")
    @classmethod
    def normalize_selected_topics(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return sorted({item.strip() for item in value if item.strip()})

    @field_validator("selected_terms")
    @classmethod
    def normalize_selected_terms(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return sorted({item.lower().strip() for item in value if item.strip()})

    @model_validator(mode="after")
    def validate_ngrams(self) -> "TopicLandscapeRequest":
        if self.ngram_min > self.ngram_max:
            raise ValueError("ngram_min cannot be greater than ngram_max")
        return self


class CitationOverviewRequest(DatasetAnalysisRequest):
    """Lightweight citation and reference overview for a works dataset."""

    top_papers: int = Field(default=30, gt=0, le=500)
    top_references: int = Field(default=100, gt=0, le=5000)
    include_reference_frequency: bool = True
    include_temporal: bool = True
    year_field: str = "publication_year"


class ScienceLandscapeRequest(DatasetAnalysisRequest):
    """Run a compact multi-tool science-landscape analysis on a works dataset."""

    include: list[ScienceLandscapeComponent] = Field(
        default_factory=lambda: ["bibliometrics", "macro", "author_landscape", "topic_landscape", "citation_overview"],
        json_schema_extra={
            "default": ["bibliometrics", "macro", "author_landscape", "topic_landscape", "citation_overview"]
        },
    )
    top_n: int = Field(default=30, gt=0, le=500)
    min_count: int | None = Field(default=None, ge=1)
    text_backend: TextBackend = "sklearn"
    modeling_backend: TopicModelingBackend = "sklearn_lda"
    nr_topics: int | None = Field(default=None, ge=2, le=200)
    max_docs: int | None = Field(default=None, gt=0)
    skip_unready: bool = True

    @field_validator("include")
    @classmethod
    def deduplicate_include(cls, value: list[ScienceLandscapeComponent]) -> list[ScienceLandscapeComponent]:
        return sorted(set(value))
