from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from langchain_core.embeddings import Embeddings


INDEX_SCHEMA_VERSION = 1
INDEX_MANIFEST_FILENAME = "index.manifest.json"


class VectorIndexUnavailableError(RuntimeError):
    """Raised when retrieval cannot run because the vector index is unhealthy."""

    code = "INDEX_UNAVAILABLE"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NormalizedEmbeddings(Embeddings):
    """Normalize vectors so inner-product search behaves like cosine similarity."""

    def __init__(self, embeddings: Embeddings):
        self.embeddings = embeddings

    @staticmethod
    def _normalize(vector: Sequence[float]) -> List[float]:
        values = [float(value) for value in vector]
        magnitude = math.sqrt(sum(value * value for value in values))
        if magnitude == 0:
            return values
        return [value / magnitude for value in values]

    def embed_documents(self, texts: Iterable[str]) -> List[List[float]]:
        return [self._normalize(vector) for vector in self.embeddings.embed_documents(texts)]

    def embed_query(self, text: str) -> List[float]:
        return self._normalize(self.embeddings.embed_query(text))


@dataclass(frozen=True)
class IndexManifest:
    schema_version: int
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    built_at: str
    document_count: int
    chunk_count: int
    source_policy: str

    @classmethod
    def build(
        cls,
        *,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimension: int,
        document_count: int,
        chunk_count: int,
        source_policy: str = "active_completed",
    ) -> "IndexManifest":
        return cls(
            schema_version=INDEX_SCHEMA_VERSION,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
            built_at=datetime.now(timezone.utc).isoformat(),
            document_count=document_count,
            chunk_count=chunk_count,
            source_policy=source_policy,
        )

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "IndexManifest":
        required = {
            "schema_version",
            "embedding_provider",
            "embedding_model",
            "embedding_dimension",
            "built_at",
            "document_count",
            "chunk_count",
            "source_policy",
        }
        missing = sorted(required.difference(value))
        if missing:
            raise ValueError(f"index manifest missing fields: {', '.join(missing)}")
        manifest = cls(
            schema_version=int(value["schema_version"]),
            embedding_provider=str(value["embedding_provider"]),
            embedding_model=str(value["embedding_model"]),
            embedding_dimension=int(value["embedding_dimension"]),
            built_at=str(value["built_at"]),
            document_count=int(value["document_count"]),
            chunk_count=int(value["chunk_count"]),
            source_policy=str(value["source_policy"]),
        )
        if manifest.schema_version != INDEX_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported index schema {manifest.schema_version}; "
                f"expected {INDEX_SCHEMA_VERSION}"
            )
        if manifest.embedding_dimension <= 0:
            raise ValueError("embedding_dimension must be positive")
        return manifest

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def is_compatible(
        self,
        *,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimension: int,
    ) -> bool:
        return (
            self.schema_version == INDEX_SCHEMA_VERSION
            and self.embedding_provider == embedding_provider
            and self.embedding_model == embedding_model
            and self.embedding_dimension == embedding_dimension
        )


def manifest_path(directory: str | Path) -> Path:
    return Path(directory) / INDEX_MANIFEST_FILENAME


def load_manifest(directory: str | Path) -> Optional[IndexManifest]:
    path = manifest_path(directory)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return IndexManifest.from_dict(json.load(handle))


def write_manifest(directory: str | Path, manifest: IndexManifest) -> None:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_path(target_dir)
    temporary_path = path.with_suffix(".json.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest.to_dict(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary_path, path)
