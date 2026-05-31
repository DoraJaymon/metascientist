"""Local output storage helpers."""

from .output_writer import OutputWriter
from .saved_dataset import SavedDataset

Dataset = SavedDataset

__all__ = ["Dataset", "OutputWriter", "SavedDataset"]
