from __future__ import annotations

import asyncio
import json

import metasci_universe as ms
from metasci_universe.analysis.topic_modeling import _ensure_numba_cache_dir


def _sample_works():
    return [
        {
            "id": "W1",
            "title": "Science mapping with language models",
            "abstract": "Language models support science mapping and bibliometric discovery.",
            "publication_year": 2023,
            "type": "article",
            "cited_by_count": 10,
            "is_oa": True,
            "doi": "10.123/a",
            "source": {"id": "S1", "name": "Journal A", "type": "journal"},
            "topics": [{"id": "T1", "name": "Science Mapping", "score": 0.9}],
            "authors": [
                {
                    "id": "A1",
                    "display_name": "Ada Lovelace",
                    "author_position": "first",
                    "is_corresponding": True,
                    "institutions": [{"id": "I1", "display_name": "Example University", "country_code": "US"}],
                },
                {
                    "id": "A2",
                    "display_name": "Grace Hopper",
                    "author_position": "last",
                    "institutions": [{"id": "I2", "display_name": "Tech Institute", "country_code": "GB"}],
                },
            ],
            "referenced_works": ["W0", "W00"],
        },
        {
            "id": "W2",
            "title": "Topic modeling for research evaluation",
            "abstract": "Topic modeling and co word analysis improve research evaluation workflows.",
            "publication_year": 2024,
            "type": "article",
            "cited_by_count": 4,
            "is_oa": False,
            "doi": "10.123/b",
            "source": {"id": "S1", "name": "Journal A", "type": "journal"},
            "topics": [{"id": "T2", "name": "Topic Modeling", "score": 0.85}],
            "authors": [
                {
                    "id": "A1",
                    "display_name": "Ada Lovelace",
                    "author_position": "first",
                    "institutions": [{"id": "I1", "display_name": "Example University", "country_code": "US"}],
                }
            ],
            "referenced_works": ["W0"],
        },
        {
            "id": "W3",
            "title": "Institutional collaboration in scientometrics",
            "abstract": "Scientometrics studies institutional collaboration, citation impact, and countries.",
            "publication_year": 2024,
            "type": "review",
            "cited_by_count": 1,
            "is_oa": True,
            "doi": "10.123/c",
            "source": {"id": "S2", "name": "Journal B", "type": "journal"},
            "topics": [{"id": "T3", "name": "Scientometrics", "score": 0.75}],
            "authors": [
                {
                    "id": "A3",
                    "display_name": "Katherine Johnson",
                    "author_position": "first",
                    "institutions": [{"id": "I3", "display_name": "Science Lab", "country_code": "US"}],
                }
            ],
            "referenced_works": [],
        },
    ]


def _write_dataset(tmp_path):
    path = tmp_path / "papers.json"
    path.write_text(json.dumps(_sample_works()), encoding="utf-8")
    return path


def test_analysis_tools_are_registered() -> None:
    tools = ms.list_tools()
    assert "analysis.bibliometrics" in tools
    assert "analysis.macro" in tools
    assert "analysis.author_landscape" in tools
    assert "analysis.coword" in tools
    assert "analysis.topic_landscape" in tools
    assert "analysis.topic_modeling" in tools
    assert "analysis.preflight" in tools
    assert "analysis.science_landscape" not in tools


def test_bibliometrics_python_api_writes_artifacts(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    result = asyncio.run(ms.analysis.bibliometrics(str(dataset), output_dir=str(tmp_path / "out")))

    assert result.data["overview"]["total_papers"] == 3
    assert result.data["overview"]["median_citations"] == 4
    assert "citation_percentiles" in result.data["overview"]
    assert result.data["annual_impact"]["annual_data"][-1]["cumulative_papers"] == 3
    assert result.data["annual_impact"]["annual_data"][-1]["cumulative_citations"] == 15
    assert result.data["most_productive_authors"]["authors"][0]["name"] == "Ada Lovelace"
    assert "analysis_json" in result.artifacts
    assert "annual_impact_csv" in result.artifacts
    assert "annual_publications_and_citations_html" in result.artifacts
    assert "cumulative_publications_html" in result.artifacts
    assert "top_authors_csv" in result.artifacts
    assert "top_authors_html" in result.artifacts


def test_macro_and_coword_python_api(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)

    macro_result = asyncio.run(ms.analysis.macro(str(dataset), output_dir=str(tmp_path / "macro")))
    assert macro_result.data["overview"]["country_count"] == 2
    assert macro_result.data["overview"]["international_collaboration_share"] > 0
    assert macro_result.data["countries"][0]["country_code"] == "US"
    assert "countries_html" not in macro_result.artifacts
    assert "institutions_html" not in macro_result.artifacts
    assert "country_collaboration_network_html" not in macro_result.artifacts
    assert "country_collaboration_chord_html" in macro_result.artifacts
    assert "corresponding_author_countries_csv" in macro_result.artifacts
    assert "corresponding_author_countries_html" in macro_result.artifacts
    assert "country_distribution_figure_html" not in macro_result.artifacts
    assert "country_productivity_map_html" in macro_result.artifacts
    assert "institution_timeline_html" in macro_result.artifacts
    assert "figure4a_top_institutions_html" in macro_result.artifacts
    assert "figure4b_institution_collaboration_network_html" in macro_result.artifacts
    assert "figure4c_institution_country_density_downgraded_html" in macro_result.artifacts
    assert "institution_collaboration_network_html" not in macro_result.artifacts
    assert "institution_country_density_csv" in macro_result.artifacts
    assert "country_by_year_matrix_csv" in macro_result.artifacts
    assert macro_result.data["institution_country_density"][0]["country_code"] == "US"
    assert macro_result.data["corresponding_author_countries"][0]["country_code"] == "US"
    assert macro_result.data["corresponding_author_countries"][0]["mcp"] == 1

    coword_result = asyncio.run(
        ms.analysis.coword(str(dataset), min_term_count=1, min_edge_weight=1, output_dir=str(tmp_path / "coword"))
    )
    assert coword_result.data["overview"]["term_count"] > 0
    assert coword_result.data["overview"]["edge_count"] > 0
    assert coword_result.data["top_keywords"]
    assert coword_result.data["clusters"]
    assert "coword_network_html" in coword_result.artifacts
    assert "coword_clusters_csv" in coword_result.artifacts
    assert "coword_cluster_network_html" in coword_result.artifacts
    assert "top_25_keywords_html" in coword_result.artifacts
    assert "keyword_wordcloud_html" in coword_result.artifacts
    assert "term_evolution_stacked_html" in coword_result.artifacts
    assert "term_by_year_matrix_csv" in coword_result.artifacts


def test_coword_filters_mathml_and_generic_terms(tmp_path) -> None:
    records = [
        {
            "id": "W1",
            "title": "Quantum spin liquids and neutron scattering",
            "abstract": "mml mrow mi math display inline Quantum spin liquids reveal magnetic frustration.",
            "publication_year": 2023,
            "cited_by_count": 5,
        },
        {
            "id": "W2",
            "title": "Quantum spin liquids in frustrated magnets",
            "abstract": "Research study results using mml mrow mi math. Neutron scattering probes spin liquids.",
            "publication_year": 2024,
            "cited_by_count": 3,
        },
    ]
    dataset = tmp_path / "mathml.json"
    dataset.write_text(json.dumps(records), encoding="utf-8")

    result = asyncio.run(
        ms.analysis.coword(
            str(dataset),
            text_backend="sklearn",
            min_term_count=1,
            min_edge_weight=1,
            output_dir=str(tmp_path / "coword_mathml"),
        )
    )
    terms = {row["term"] for row in result.data["terms"]}

    assert "quantum" in terms
    assert "spin" in terms
    assert "mml" not in terms
    assert "mrow" not in terms
    assert "math" not in terms
    assert "research" not in terms


def test_coword_keybert_extraction_records_provenance(tmp_path) -> None:
    records = [
        {
            "id": "W1",
            "title": "Quantum spin liquids and neutron scattering",
            "abstract": "Quantum spin liquids reveal magnetic frustration in frustrated magnets.",
            "publication_year": 2023,
            "cited_by_count": 5,
        },
        {
            "id": "W2",
            "title": "Neutron scattering probes quantum spin liquids",
            "abstract": "Frustrated magnets and quantum spin liquids are studied with neutron scattering.",
            "publication_year": 2024,
            "cited_by_count": 3,
        },
    ]
    dataset = tmp_path / "keybert.json"
    dataset.write_text(json.dumps(records), encoding="utf-8")

    result = asyncio.run(
        ms.analysis.coword(
            str(dataset),
            term_extraction="keybert",
            keyphrase_embedding_backend="spacy",
            keyphrase_top_n=8,
            min_term_count=1,
            min_edge_weight=1,
            output_dir=str(tmp_path / "coword_keybert"),
        )
    )
    terms = {row["term"] for row in result.data["terms"]}

    assert result.data["overview"]["term_extraction"] == "keybert"
    assert any("quantum spin" in term or "spin liquids" in term for term in terms)
    assert result.data["keyphrase_provenance"]
    assert "keyphrase_provenance_csv" in result.artifacts


def test_coword_keybert_filters_rhetorical_title_phrases(tmp_path) -> None:
    records = [
        {
            "id": "W1",
            "title": "We prove the existence of p-adic L-functions for abelian varieties",
            "publication_year": 2020,
        },
        {
            "id": "W2",
            "title": "A new proof of p-adic L-functions and abelian varieties",
            "publication_year": 2021,
        },
        {
            "id": "W3",
            "title": "Questions on the existence of p-adic L-functions",
            "publication_year": 2022,
        },
    ]
    dataset = tmp_path / "keybert_math_titles.json"
    dataset.write_text(json.dumps(records), encoding="utf-8")

    result = asyncio.run(
        ms.analysis.coword(
            str(dataset),
            term_extraction="keybert",
            keyphrase_embedding_backend="spacy",
            keyphrase_top_n=6,
            min_term_count=1,
            min_edge_weight=1,
            output_dir=str(tmp_path / "coword_keybert_math_titles"),
        )
    )
    terms = {row["term"] for row in result.data["terms"]}

    assert "p adic l functions" in terms
    assert "abelian varieties" in terms
    assert "prove the existence" not in terms
    assert "questions on the existence" not in terms


def test_coword_tfidf_keyphrase_extraction_uses_corpus_signal(tmp_path) -> None:
    records = [
        {
            "id": "W1",
            "title": "Open access research outputs receive diverse citations",
            "abstract": "Open access status is associated with citation diversity and broader scholarly audiences.",
            "publication_year": 2023,
        },
        {
            "id": "W2",
            "title": "Citation diversity in open access publications",
            "abstract": "Open access publications show diverse citation sources across institutions and regions.",
            "publication_year": 2024,
        },
        {
            "id": "W3",
            "title": "Dataset citation coverage in bibliographic databases",
            "abstract": "Dataset citation coverage differs across scholarly databases and metadata sources.",
            "publication_year": 2024,
        },
    ]
    dataset = tmp_path / "tfidf_keyphrase.json"
    dataset.write_text(json.dumps(records), encoding="utf-8")

    result = asyncio.run(
        ms.analysis.coword(
            str(dataset),
            term_extraction="tfidf_keyphrase",
            keyphrase_top_n=6,
            keyphrase_candidate_limit=80,
            min_term_count=1,
            min_edge_weight=1,
            output_dir=str(tmp_path / "coword_tfidf_keyphrase"),
        )
    )
    terms = {row["term"] for row in result.data["terms"]}

    assert result.data["overview"]["term_extraction"] == "tfidf_keyphrase"
    assert "open access" in terms
    assert any("citation" in term for term in terms)
    assert result.data["keyphrase_provenance"]
    assert "keyphrase_provenance_csv" in result.artifacts


def test_author_landscape_python_api(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    result = asyncio.run(ms.analysis.author_landscape(str(dataset), output_dir=str(tmp_path / "authors")))

    assert result.command == "analysis.author_landscape"
    assert result.data["overview"]["total_authors"] == 3
    assert result.data["authors"][0]["name"] == "Ada Lovelace"
    assert result.data["authors"][0]["first_author_papers"] == 2
    assert result.data["authors"][0]["corresponding_author_papers"] == 1
    assert result.data["author_collaboration"][0]["source"] == "Ada Lovelace"
    assert "author_collaboration_network_html" in result.artifacts
    assert "author_roles_csv" in result.artifacts


def test_topic_landscape_and_modeling_tool(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    result = asyncio.run(
        ms.run_tool(
            "analysis.topic_landscape",
            {
                "dataset_path": str(dataset),
                "min_count": 1,
                "modeling_backend": "sklearn_lda",
                "nr_topics": 2,
                "selected_topics": ["Science Mapping"],
                "selected_terms": ["language models"],
                "output_dir": str(tmp_path / "topics"),
            },
        )
    )

    assert result.data["openalex_topics"]["topics"]
    assert result.data["coword"]["terms"]
    assert result.data["topic_modeling"]["topics"]
    assert result.data["topic_modeling"]["representative_docs"]
    assert "modeled_topics_html" in result.artifacts
    assert "openalex_topic_evolution_stacked_html" in result.artifacts
    assert "openalex_topic_by_year_matrix_csv" in result.artifacts
    assert "coword_term_evolution_stacked_html" in result.artifacts


def test_citation_overview_python_api(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    result = asyncio.run(ms.analysis.citation_overview(str(dataset), output_dir=str(tmp_path / "citations")))

    assert result.data["overview"]["total_citations"] == 15
    assert result.data["top_references"][0]["referenced_work"] == "W0"


def test_inspect_readiness_tool(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    result = asyncio.run(
        ms.run_tool(
            "analysis.inspect_readiness",
            {"dataset_path": str(dataset), "output_dir": str(tmp_path / "readiness")},
        )
    )

    assert result.data["overview"]["total_papers"] == 3
    assert any(row["tool"] == "analysis.macro" and row["status"] == "ready" for row in result.data["tools"])
    assert any(row["tool"] == "analysis.author_landscape" and row["status"] == "ready" for row in result.data["tools"])
    assert "field_coverage_csv" in result.artifacts


def test_analysis_preflight_python_api(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    result = asyncio.run(ms.analysis.preflight(str(dataset), intent="science_landscape"))

    assert result.command == "analysis.preflight"
    assert "analysis.bibliometrics" in result.data["overview"]["recommended_tools"]
    assert "analysis.author_landscape" in result.data["overview"]["recommended_tools"]
    assert "analysis.topic_landscape" in result.data["overview"]["recommended_tools"]
    assert result.data["safe_defaults"]["text_backend"] == "sklearn"
    assert result.data["safe_defaults"]["modeling_backend"] == "sklearn_lda"
    assert result.data["safe_defaults"]["min_count"] == 1


def test_analysis_recommend_alias_is_kept(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    result = asyncio.run(ms.analysis.recommend(str(dataset), intent="science_landscape"))

    assert result.command == "analysis.recommend"
    assert "analysis.bibliometrics" in result.data["overview"]["recommended_tools"]


def test_workflow_science_landscape_runs_composed_scenario(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    result = asyncio.run(
        ms.workflows.science_landscape(
            str(dataset),
            output_dir=str(tmp_path / "landscape"),
            top_n=5,
        )
    )

    assert result.command == "workflows.science_landscape"
    assert result.data["overview"]["total_papers"] == 3
    assert "bibliometrics" in result.data["components"]
    assert "author_landscape" in result.data["components"]
    assert "topic_landscape" in result.data["components"]
    assert result.data["components"]["author_landscape"]["authors"]
    assert result.data["components"]["topic_landscape"]["modeled_topics"]
    assert "summary_md" in result.artifacts


def test_preflight_tool_is_registered(tmp_path) -> None:
    dataset = _write_dataset(tmp_path)
    card = ms.describe_tool("analysis.preflight")
    assert card["name"] == "analysis.preflight"

    result = asyncio.run(
        ms.run_tool(
            "analysis.preflight",
            {"dataset_path": str(dataset), "intent": "science_landscape"},
        )
    )
    assert "analysis.citation_overview" in result.data["overview"]["recommended_tools"]


def test_numba_cache_dir_default_is_writable(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("NUMBA_CACHE_DIR", raising=False)
    monkeypatch.setenv("METASCI_NUMBA_CACHE_DIR", str(tmp_path))
    diagnostics: list[str] = []

    _ensure_numba_cache_dir(diagnostics)

    assert diagnostics == []
    assert (tmp_path / "metasci-numba-cache").exists()
