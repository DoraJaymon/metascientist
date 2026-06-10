"""Co-word analysis for scholarly works datasets."""

from __future__ import annotations

from collections import Counter, defaultdict
import re
from typing import Any

import networkx as nx

from metasci_universe.analysis import _normalize as norm
from metasci_universe.analysis._artifacts import save_analysis_artifacts
from metasci_universe.analysis._dataset import load_records
from metasci_universe.analysis._keyphrases import (
    KeyphraseConfig,
    extract_keyphrases_for_corpus,
    merge_keyphrase_aliases_llm,
    refine_keyphrases_for_corpus_llm,
)
from metasci_universe.analysis._text import TextProcessor, build_text_processor, count_edges, edge_rows
from metasci_universe.analysis._viz import bar, bubble_terms, line, network, stacked_area, wide_matrix
from metasci_universe.schemas.analysis import CoWordAnalysisRequest
from metasci_universe.schemas.common import MetaSciResult


async def coword(
    dataset_path: str,
    *,
    text_fields: list[str] | None = None,
    text_backend: str = "sklearn",
    language: str = "en",
    spacy_model: str | None = None,
    lemmatize: bool = True,
    ngram_min: int = 1,
    ngram_max: int = 2,
    min_term_count: int = 3,
    min_edge_weight: int = 2,
    top_terms: int = 100,
    top_edges: int = 300,
    stopwords: list[str] | None = None,
    term_extraction: str = "ngram",
    keyphrase_top_n: int = 12,
    keyphrase_candidate_limit: int = 80,
    keyphrase_embedding_backend: str = "spacy",
    keyphrase_embedding_model: str | None = None,
    keyphrase_embedding_api_base_url: str | None = None,
    keyphrase_embedding_api_key_env: str | None = "OPENAI_API_KEY",
    keyphrase_merge_llm: bool = False,
    keyphrase_merge_model: str | None = None,
    keyphrase_merge_api_base_url: str | None = None,
    keyphrase_merge_api_key_env: str | None = "OPENAI_API_KEY",
    include_evolution: bool = True,
    year_field: str = "publication_year",
    output_dir: str | None = None,
) -> MetaSciResult:
    """Run co-word and term co-occurrence analysis."""
    request = CoWordAnalysisRequest(
        dataset_path=dataset_path,
        text_fields=text_fields or ["title", "abstract"],
        text_backend=text_backend,  # type: ignore[arg-type]
        language=language,
        spacy_model=spacy_model,
        lemmatize=lemmatize,
        ngram_min=ngram_min,
        ngram_max=ngram_max,
        min_term_count=min_term_count,
        min_edge_weight=min_edge_weight,
        top_terms=top_terms,
        top_edges=top_edges,
        stopwords=stopwords or [],
        term_extraction=term_extraction,  # type: ignore[arg-type]
        keyphrase_top_n=keyphrase_top_n,
        keyphrase_candidate_limit=keyphrase_candidate_limit,
        keyphrase_embedding_backend=keyphrase_embedding_backend,  # type: ignore[arg-type]
        keyphrase_embedding_model=keyphrase_embedding_model,
        keyphrase_embedding_api_base_url=keyphrase_embedding_api_base_url,
        keyphrase_embedding_api_key_env=keyphrase_embedding_api_key_env,
        keyphrase_merge_llm=keyphrase_merge_llm,
        keyphrase_merge_model=keyphrase_merge_model,
        keyphrase_merge_api_base_url=keyphrase_merge_api_base_url,
        keyphrase_merge_api_key_env=keyphrase_merge_api_key_env,
        include_evolution=include_evolution,
        year_field=year_field,
        output_dir=output_dir,
    )
    records, dataset_metadata, resolved_path = load_records(request.dataset_path)
    precomputed_keyphrases = None
    keyphrase_llm_refine: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    if request.term_extraction in {"keybert", "tfidf_keyphrase"}:
        precomputed_keyphrases, precompute_diagnostics = _precompute_keyphrases(records, request)
        diagnostics.extend(precompute_diagnostics)
        if request.keyphrase_merge_llm:
            if not request.keyphrase_merge_model:
                diagnostics.append("keyphrase_merge_llm=True but no keyphrase_merge_model was provided; skipped LLM keyphrase refine.")
            else:
                llm_papers = [{"title": norm.title(work), "abstract": norm.abstract_text(work)} for work in records]
                llm_candidate_rows = [precomputed_keyphrases.get(index, []) for index in range(len(records))]
                skipped_without_abstract = 0
                for index, paper in enumerate(llm_papers):
                    if not paper["abstract"].strip():
                        llm_candidate_rows[index] = []
                        skipped_without_abstract += 1
                if skipped_without_abstract:
                    diagnostics.append(
                        f"Skipped LLM keyphrase refine for {skipped_without_abstract} records without abstracts."
                    )
                refined_rows, keyphrase_llm_refine, refine_diagnostics = await refine_keyphrases_for_corpus_llm(
                    llm_papers,
                    llm_candidate_rows,
                    model=request.keyphrase_merge_model,
                    api_base_url=request.keyphrase_merge_api_base_url,
                    api_key_env=request.keyphrase_merge_api_key_env,
                    target_terms=request.keyphrase_top_n,
                )
                diagnostics.extend(refine_diagnostics)
                precomputed_keyphrases = {index: rows for index, rows in enumerate(refined_rows)}
    data, compute_diagnostics = compute_coword(
        records,
        request,
        precomputed_keyphrases=precomputed_keyphrases,
        keyphrase_llm_refine=keyphrase_llm_refine,
    )
    diagnostics.extend(compute_diagnostics)
    if request.keyphrase_merge_llm and request.term_extraction in {"keybert", "tfidf_keyphrase"}:
        pass
    elif request.keyphrase_merge_llm:
        if not request.keyphrase_merge_model:
            diagnostics.append("keyphrase_merge_llm=True but no keyphrase_merge_model was provided; skipped LLM alias merge.")
        else:
            terms_for_merge = [row["term"] for row in data.get("terms", [])[: min(200, len(data.get("terms", [])))]]
            alias_mapping, merge_diagnostics = await merge_keyphrase_aliases_llm(
                terms_for_merge,
                model=request.keyphrase_merge_model,
                api_base_url=request.keyphrase_merge_api_base_url,
                api_key_env=request.keyphrase_merge_api_key_env,
            )
            diagnostics.extend(merge_diagnostics)
            if alias_mapping:
                data, recompute_diagnostics = compute_coword(records, request, alias_mapping=alias_mapping)
                diagnostics.extend(recompute_diagnostics)
                data["alias_mapping"] = [
                    {"term": term, "canonical_term": canonical}
                    for term, canonical in sorted(alias_mapping.items())
                    if term != canonical
                ]
    input_payload = request.model_dump(mode="json")
    artifacts = save_analysis_artifacts(
        command="analysis.coword",
        input_payload=input_payload,
        data=data,
        summary_markdown=_summary_markdown(data, resolved_path=resolved_path, diagnostics=diagnostics),
        tables={
            "terms": data["terms"],
            "top_keywords": data["top_keywords"],
            "coword_clusters": data["clusters"],
            "coword_edges": data["edges"],
            "term_by_year": data["term_by_year"],
            "term_by_year_matrix": data["term_by_year_matrix"],
            "keyphrase_provenance": data.get("keyphrase_provenance", []),
            "keyphrase_alias_mapping": data.get("alias_mapping", []),
            "keyphrase_llm_refine": data.get("keyphrase_llm_refine", []),
        },
        figures=_figures(data),
        output_dir=request.output_dir,
        diagnostics=diagnostics,
    )
    return MetaSciResult(
        command="analysis.coword",
        input=input_payload,
        data=data,
        artifacts=artifacts,
        metadata={
            "record_count": len(records),
            "dataset_path": resolved_path,
            "dataset_schema": dataset_metadata.get("schema_name"),
        },
        diagnostics=diagnostics,
    )


def compute_coword(
    works: list[dict[str, Any]],
    request: CoWordAnalysisRequest,
    *,
    alias_mapping: dict[str, str] | None = None,
    precomputed_keyphrases: dict[int, list[dict[str, Any]]] | None = None,
    keyphrase_llm_refine: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Compute co-word analysis data without writing artifacts."""
    diagnostics: list[str] = []
    processor = build_text_processor(
        backend=request.text_backend,
        language=request.language,
        spacy_model=request.spacy_model,
        stopwords=request.stopwords,
        lemmatize=request.lemmatize,
    )
    diagnostics.extend(processor.diagnostics)
    term_counter: Counter[str] = Counter()
    dropped_counter: Counter[str] = Counter()
    doc_counter: Counter[str] = Counter()
    docs_terms: list[list[str]] = []
    term_year_counter: Counter[tuple[int, str]] = Counter()
    keyphrase_provenance: list[dict[str, Any]] = []
    docs_with_text = 0
    keyphrase_config = KeyphraseConfig(
        top_n=request.keyphrase_top_n,
        candidate_limit=request.keyphrase_candidate_limit,
        embedding_backend=request.keyphrase_embedding_backend,
        embedding_model=request.keyphrase_embedding_model,
        embedding_api_base_url=request.keyphrase_embedding_api_base_url,
        embedding_api_key_env=request.keyphrase_embedding_api_key_env,
        merge_llm=request.keyphrase_merge_llm,
        merge_model=request.keyphrase_merge_model,
        merge_api_base_url=request.keyphrase_merge_api_base_url,
        merge_api_key_env=request.keyphrase_merge_api_key_env,
        language=request.language,
        spacy_model=request.spacy_model,
        stopwords=set(request.stopwords),
    )
    if request.term_extraction in {"keybert", "tfidf_keyphrase"} and precomputed_keyphrases is None:
        precomputed_keyphrases, precompute_diagnostics = _precompute_keyphrases(works, request)
        diagnostics.extend(precompute_diagnostics)
    keyphrase_llm_refine = keyphrase_llm_refine or []

    for index, work in enumerate(works):
        raw_terms, raw_provenance, extraction_diagnostics = _terms_for_work(
            work,
            request,
            processor=processor,
            keyphrase_config=keyphrase_config,
            precomputed_keyphrases=precomputed_keyphrases.get(index) if precomputed_keyphrases is not None else None,
        )
        diagnostics.extend(extraction_diagnostics)
        terms = _clean_terms(raw_terms, dropped_counter, alias_mapping=alias_mapping)
        if not terms:
            docs_terms.append([])
            continue
        docs_with_text += 1
        docs_terms.append(terms)
        term_counter.update(terms)
        unique_terms = set(terms)
        doc_counter.update(unique_terms)
        publication_year = norm.year(work, request.year_field)
        for row in raw_provenance:
            normalized = _normalize_term(str(row.get("term") or ""))
            if alias_mapping:
                normalized = _normalize_term(alias_mapping.get(normalized, normalized))
            if not normalized or _is_low_signal(normalized):
                continue
            keyphrase_provenance.append(
                {
                    "paper_index": index,
                    "work_id": norm.work_id(work),
                    "year": publication_year,
                    "title": norm.title(work),
                    "raw_keyword": row.get("raw_term") or row.get("term"),
                    "normalized_keyword": normalized,
                    "source": row.get("source") or "title_abstract_phrase",
                    "score": row.get("score"),
                    "tfidf_score": row.get("tfidf_score"),
                    "doc_frequency": row.get("doc_frequency"),
                    "candidate_sources": row.get("candidate_sources"),
                    "is_proper_noun": row.get("is_proper_noun"),
                    "is_noun_chunk": row.get("is_noun_chunk"),
                    "is_single_token": row.get("is_single_token"),
                }
            )
        if publication_year is not None and request.include_evolution:
            for term in unique_terms:
                term_year_counter[(publication_year, term)] += 1

    if docs_with_text == 0:
        diagnostics.append("No usable title, abstract, or topic text found for co-word analysis.")

    allowed_terms = {
        term
        for term, count in term_counter.items()
        if count >= request.min_term_count and len(term) > 1 and not _is_low_signal(term)
    }
    edges = count_edges(docs_terms, allowed_terms)
    edge_data = edge_rows(edges, top_edges=request.top_edges, min_edge_weight=request.min_edge_weight)

    graph = nx.Graph()
    for edge in edge_data:
        graph.add_edge(edge["source"], edge["target"], weight=edge["weight"])
    degree = dict(graph.degree())
    weighted_degree = dict(graph.degree(weight="weight"))
    clusters, node_clusters = _cluster_terms(graph, term_counter=term_counter, doc_counter=doc_counter, works=works, docs_terms=docs_terms)

    terms = []
    for rank, (term, count) in enumerate(term_counter.most_common(), start=1):
        if term not in allowed_terms:
            continue
        terms.append(
            {
                "rank": len(terms) + 1,
                "term": term,
                "count": count,
                "doc_count": doc_counter[term],
                "degree": degree.get(term, 0),
                "weighted_degree": round(float(weighted_degree.get(term, 0)), 3),
            }
        )
        if len(terms) >= request.top_terms:
            break

    top_term_names = {row["term"] for row in terms[: min(30, len(terms))]}
    if request.selected_terms:
        top_term_names.update(request.selected_terms)
    term_by_year = [
        {"year": year, "term": term, "count": count}
        for (year, term), count in sorted(term_year_counter.items())
        if term in top_term_names
    ]

    return (
        {
            "overview": {
                "total_papers": len(works),
                "docs_with_text": docs_with_text,
                "term_count": len(terms),
                "edge_count": len(edge_data),
                "text_fields": request.text_fields,
                "text_backend": request.text_backend,
                "term_extraction": request.term_extraction,
                "keyphrase_embedding_backend": request.keyphrase_embedding_backend,
                "keyphrase_embedding_model": request.keyphrase_embedding_model,
                "keyphrase_merge_llm": request.keyphrase_merge_llm,
                "spacy_model": request.spacy_model,
                "lemmatize": request.lemmatize,
                "ngram_range": [request.ngram_min, request.ngram_max],
            },
            "terms": terms,
            "top_keywords": terms[:25],
            "clusters": clusters,
            "edges": edge_data,
            "term_by_year": term_by_year,
            "term_by_year_matrix": wide_matrix(term_by_year, index="year", columns="term", values="count"),
            "node_clusters": node_clusters,
            "dropped_terms": [
                {"term": term, "count": count}
                for term, count in dropped_counter.most_common(50)
            ],
            "keyphrase_provenance": keyphrase_provenance[: max(1000, request.top_terms * 20)],
            "keyphrase_llm_refine": keyphrase_llm_refine,
        },
        diagnostics,
    )


def _precompute_keyphrases(
    works: list[dict[str, Any]],
    request: CoWordAnalysisRequest,
) -> tuple[dict[int, list[dict[str, Any]]], list[str]]:
    keyphrase_config = KeyphraseConfig(
        top_n=request.keyphrase_top_n,
        candidate_limit=request.keyphrase_candidate_limit,
        embedding_backend=request.keyphrase_embedding_backend,
        embedding_model=request.keyphrase_embedding_model,
        embedding_api_base_url=request.keyphrase_embedding_api_base_url,
        embedding_api_key_env=request.keyphrase_embedding_api_key_env,
        merge_llm=request.keyphrase_merge_llm,
        merge_model=request.keyphrase_merge_model,
        merge_api_base_url=request.keyphrase_merge_api_base_url,
        merge_api_key_env=request.keyphrase_merge_api_key_env,
        language=request.language,
        spacy_model=request.spacy_model,
        stopwords=set(request.stopwords),
    )
    corpus_texts = [
        norm.text_for_fields(work, [field for field in request.text_fields if field != "topics"])
        for work in works
    ]
    corpus_keyphrases, diagnostics = extract_keyphrases_for_corpus(
        corpus_texts,
        keyphrase_config,
        method=request.term_extraction,
    )
    return {index: rows for index, rows in enumerate(corpus_keyphrases)}, diagnostics


def _terms_for_work(
    work: dict[str, Any],
    request: CoWordAnalysisRequest,
    *,
    processor: TextProcessor,
    keyphrase_config: KeyphraseConfig,
    precomputed_keyphrases: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    terms: list[str] = []
    provenance: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    text_fields = [field for field in request.text_fields if field != "topics"]
    text = norm.text_for_fields(work, text_fields)
    if text:
        if request.term_extraction in {"keybert", "tfidf_keyphrase"}:
            rows = precomputed_keyphrases or []
            for row in rows:
                terms.append(str(row["term"]))
                provenance.append({"term": row["term"], "raw_term": row["term"], **row})
        else:
            terms.extend(processor.terms(text, ngram_min=request.ngram_min, ngram_max=request.ngram_max))
    if "topics" in request.text_fields:
        terms.extend(topic["name"].strip().lower() for topic in norm.topics(work) if topic.get("name"))
    return [term for term in terms if term], provenance, diagnostics


def _is_low_signal(term: str) -> bool:
    tokens = term.split()
    if not tokens:
        return True
    if all(len(token) <= 2 for token in tokens):
        return True
    if any(token in _MATHML_STOPWORDS for token in tokens):
        return True
    if term in _BIBLIOMETRIC_STOPWORDS:
        return True
    return False


_MATHML_STOPWORDS = {
    "accent",
    "annotation",
    "display",
    "false",
    "http",
    "inline",
    "math",
    "mathml",
    "mathvariant",
    "mathjax",
    "mi",
    "mn",
    "mo",
    "mover",
    "mprescripts",
    "mrow",
    "msub",
    "msup",
    "msubsup",
    "mfrac",
    "mstyle",
    "msqrt",
    "mml",
    "mmultiscripts",
    "mtext",
    "none",
    "normal",
    "org",
    "semantics",
    "stretchy",
    "w3",
    "www",
    "xmlns",
}

_BIBLIOMETRIC_STOPWORDS = {
    "abstract",
    "analysis",
    "article",
    "articles",
    "based",
    "conclusion",
    "data",
    "findings",
    "method",
    "methods",
    "paper",
    "papers",
    "publication",
    "publications",
    "research",
    "researchers",
    "result",
    "results",
    "science",
    "scientific",
    "study",
    "studies",
    "using",
}


def _clean_terms(
    terms: list[str],
    dropped_counter: Counter[str],
    *,
    alias_mapping: dict[str, str] | None = None,
) -> list[str]:
    cleaned: list[str] = []
    for term in terms:
        normalized = _normalize_term(term)
        if alias_mapping:
            normalized = _normalize_term(alias_mapping.get(normalized, normalized))
        if not normalized or _is_low_signal(normalized):
            if normalized:
                dropped_counter[normalized] += 1
            continue
        cleaned.append(normalized)
    return cleaned


def _normalize_term(term: str) -> str:
    value = term.lower()
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\\b(?:mml|mrow|mi|mn|mo|msub|msup|msubsup|mfrac|msqrt|semantics|annotation|math)\\b", " ", value)
    value = re.sub(r"[^a-z0-9 -]+", " ", value)
    value = re.sub(r"\\s+", " ", value).strip(" -")
    return value


def _cluster_terms(
    graph: nx.Graph,
    *,
    term_counter: Counter[str],
    doc_counter: Counter[str],
    works: list[dict[str, Any]],
    docs_terms: list[list[str]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not graph.nodes:
        return [], {}
    communities = list(nx.algorithms.community.greedy_modularity_communities(graph, weight="weight"))
    clusters: list[dict[str, Any]] = []
    node_metadata: dict[str, dict[str, Any]] = {}
    citations_by_term: dict[str, list[int]] = defaultdict(list)
    years_by_term: dict[str, list[int]] = defaultdict(list)
    title_by_term: dict[str, Counter[str]] = defaultdict(Counter)
    for work, terms in zip(works, docs_terms):
        unique_terms = set(terms)
        citation_count = norm.citations(work)
        publication_year = norm.year(work)
        title = norm.title(work)
        for term in unique_terms:
            citations_by_term[term].append(citation_count)
            if publication_year is not None:
                years_by_term[term].append(publication_year)
            if title:
                title_by_term[term][title] += 1

    for cluster_id, community in enumerate(sorted(communities, key=len, reverse=True), start=1):
        terms = sorted(community, key=lambda term: (term_counter[term], graph.degree(term, weight="weight")), reverse=True)
        internal_weight = 0.0
        external_weight = 0.0
        community_set = set(community)
        citations: list[int] = []
        years: list[int] = []
        representatives: Counter[str] = Counter()
        for term in terms:
            node_metadata[term] = {
                "color": cluster_id,
                "size": 10 + min(48, max(1, term_counter[term]) ** 0.5 * 4),
                "hover": f"{term}<br>Cluster {cluster_id}<br>Count {term_counter[term]}",
            }
            citations.extend(citations_by_term.get(term, []))
            years.extend(years_by_term.get(term, []))
            representatives.update(title_by_term.get(term, Counter()))
            for neighbor, attrs in graph[term].items():
                weight = float(attrs.get("weight") or 1)
                if neighbor in community_set:
                    internal_weight += weight
                else:
                    external_weight += weight
        internal_weight = internal_weight / 2
        label_terms = terms[:3]
        clusters.append(
            {
                "cluster": cluster_id,
                "label": "; ".join(label_terms),
                "term_count": len(terms),
                "top_terms": "; ".join(terms[:10]),
                "occurrence_frequency": sum(term_counter[term] for term in terms),
                "doc_frequency": sum(doc_counter[term] for term in terms),
                "total_link_strength": round(sum(float(graph.degree(term, weight="weight")) for term in terms), 3),
                "internal_link_strength": round(internal_weight, 3),
                "external_link_strength": round(external_weight, 3),
                "average_publication_year": round(sum(years) / len(years), 3) if years else None,
                "average_citations": round(sum(citations) / len(citations), 3) if citations else 0,
                "representative_papers": " | ".join(title for title, _ in representatives.most_common(3)),
            }
        )
    return clusters, node_metadata


def _figures(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "top_terms": bar(
            list(reversed(data["terms"][:30])),
            x="count",
            y="term",
            title="Top Co-Word Terms",
            orientation="h",
        ),
        "top_25_keywords": bar(
            list(reversed(data["top_keywords"][:25])),
            x="count",
            y="term",
            title="Top 25 Keywords",
            orientation="h",
        ),
        "keyword_wordcloud": bubble_terms(
            data["top_keywords"][:25],
            term="term",
            size="count",
            color="degree",
            title="Keyword Word Cloud",
        ),
        "coword_network": network(data["edges"], title="Co-Word Network"),
        "coword_cluster_network": network(
            data["edges"],
            title="Co-Word Cluster Network",
            node_metadata=data.get("node_clusters", {}),
        ),
        "term_evolution": line(
            data["term_by_year"],
            x="year",
            y="count",
            color="term",
            title="Top Term Evolution",
        ),
        "term_evolution_stacked": stacked_area(
            data["term_by_year"],
            x="year",
            y="count",
            color="term",
            title="Top Term Evolution",
        ),
    }


def _summary_markdown(data: dict[str, Any], *, resolved_path: str, diagnostics: list[str]) -> str:
    lines = [
        "# Co-Word Analysis",
        "",
        f"Dataset: `{resolved_path}`",
        "",
        f"- Papers: {data['overview']['total_papers']}",
        f"- Papers with usable text: {data['overview']['docs_with_text']}",
        f"- Terms: {data['overview']['term_count']}",
        f"- Edges: {data['overview']['edge_count']}",
    ]
    if diagnostics:
        lines.extend(["", "## Diagnostics"])
        lines.extend(f"- {item}" for item in diagnostics)
    lines.extend(["", "## Top Terms"])
    for row in data["terms"][:15]:
        lines.append(f"- {row['term']}: {row['count']}")
    if data.get("clusters"):
        lines.extend(["", "## Co-Word Clusters"])
        for row in data["clusters"][:10]:
            lines.append(
                f"- Cluster {row['cluster']} ({row['label']}): {row['term_count']} terms, TLS {row['total_link_strength']}"
            )
    return "\n".join(lines)
