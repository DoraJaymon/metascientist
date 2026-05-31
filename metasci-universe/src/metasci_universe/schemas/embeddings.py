"""Contracts for reusable embedding artifacts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from metasci_universe.schemas.analysis import TextField


EmbeddingBackend = Literal["sentence_transformers", "transformers_pooling", "spacy", "api"]


class EmbedWorksRequest(BaseModel):
    """Create reusable text embeddings for a saved works dataset."""

    model_config = ConfigDict(extra="forbid")

    dataset_path: str = Field(description="Path to a saved MetaSci works dataset file or dataset directory.")
    text_fields: list[TextField] = Field(default_factory=lambda: ["title", "abstract"])
    backend: EmbeddingBackend = "sentence_transformers"
    model: str | None = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    language: str = "en"
    batch_size: int = Field(default=32, gt=0, le=512)
    max_docs: int | None = Field(default=None, gt=0)
    min_text_words: int = Field(default=3, ge=1)
    normalize: bool = True
    dimensions: int = Field(
        default=384,
        ge=8,
        le=8192,
        description="Fallback vector size for spaCy models without vectors; API backends may ignore this.",
    )
    api_base_url: str | None = Field(default=None, description="OpenAI-compatible API base URL.")
    api_key: str | None = Field(default=None, description="Embedding API key. Prefer api_key_env for reusable scripts.")
    api_key_env: str | None = Field(default="OPENAI_API_KEY", description="Environment variable containing the API key.")
    output_dir: str | None = Field(default=None, description="Directory for embedding artifacts.")

    @field_validator("text_fields")
    @classmethod
    def deduplicate_text_fields(cls, value: list[TextField]) -> list[TextField]:
        return sorted(set(value))

    @model_validator(mode="after")
    def validate_backend_settings(self) -> "EmbedWorksRequest":
        if self.backend == "api" and not self.model:
            raise ValueError("model is required for backend='api'")
        if self.backend != "api" and (self.api_base_url or self.api_key):
            raise ValueError("api_base_url/api_key are only valid for backend='api'")
        return self
