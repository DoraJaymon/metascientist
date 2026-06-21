from __future__ import annotations

import json
from pathlib import Path

from metasci_universe.storage.output_writer import OutputWriter
from metasci_universe.storage.saved_dataset import SavedDataset


def test_artifact_writer_and_dataset_load(tmp_path) -> None:
    writer = OutputWriter(tmp_path)
    artifacts = writer.save_dataset(
        kind="works",
        command="works.search",
        input_payload={"query": "science of science"},
        records=[{"id": "W1", "title": "A paper"}],
        metadata={"provider": "openalex", "returned_count": 1},
        diagnostics=["note"],
    )

    dataset = SavedDataset.load(artifacts["data_file"])
    info = dataset.info()

    assert info["schema_name"] == "works"
    assert info["record_count"] == 1
    assert info["metadata"]["provider"] == "openalex"
    assert info["diagnostics"] == ["note"]


def test_text_artifact_writer_saves_extra_files(tmp_path) -> None:
    writer = OutputWriter(tmp_path)
    artifacts = writer.save_text_artifact(
        kind="fulltext",
        command="works.fulltext",
        input_payload={"identifier": "10.1007/example", "provider": "springer"},
        filename="fulltext.md",
        content="# Title\n",
        metadata={"provider": "springer"},
        diagnostics=[],
        extra_files={
            "work.json": {"id": "springer:10.1007/example"},
            "article.pdf": b"%PDF-1.4 example",
        },
    )

    assert Path(artifacts["text_file"]).read_text(encoding="utf-8") == "# Title\n"
    assert json.loads(Path(artifacts["work_file"]).read_text(encoding="utf-8"))["id"] == "springer:10.1007/example"
    assert Path(artifacts["pdf_file"]).read_bytes() == b"%PDF-1.4 example"
    metadata = json.loads(Path(artifacts["metadata_file"]).read_text(encoding="utf-8"))
    assert sorted(metadata["extra_files"]) == ["article.pdf", "work.json"]
    assert artifacts["work_file"].endswith("work.json")
    assert artifacts["pdf_file"].endswith("article.pdf")
