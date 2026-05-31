from __future__ import annotations

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
