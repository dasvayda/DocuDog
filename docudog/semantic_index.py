"""Optional local Zvec index for DocuDog document chunks.

This module deliberately imports neither Zvec nor an embedding runtime until
semantic search is enabled and invoked.  The default application path therefore
does not download a model, create an index, or require the optional packages.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from . import artifact_home

logger = logging.getLogger(__name__)

_LEVEL_RANK = {"P4": 0, "P3": 1, "P2": 2, "P1": 3}
_MAX_RESULTS = 50
_MANIFEST_NAME = "manifest.json"
_COLLECTION_NAME = "docudog_chunks"


class SemanticIndexError(RuntimeError):
    """Stable, user-safe error raised by the optional semantic index."""


class EmbeddingProvider(Protocol):
    dimension: int

    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class Chunk:
    text: str
    anchor: str


def settings(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("semantic_search")
    return raw if isinstance(raw, dict) else {}


def enabled(config: dict[str, Any]) -> bool:
    return bool(settings(config).get("enabled", False))


def _int_setting(cfg: dict[str, Any], name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(cfg.get(name, default)))
    except (TypeError, ValueError):
        return default


def index_path(config: dict[str, Any]) -> str:
    cfg = settings(config)
    raw = str(cfg.get("index_path") or "").strip()
    if raw:
        return os.path.normpath(os.path.expandvars(raw))
    return os.path.join(artifact_home.artifact_home(config), "semantic_index")


def indexed_levels(config: dict[str, Any]) -> set[str]:
    raw = settings(config).get("indexed_levels", ["P3", "P4"])
    if not isinstance(raw, list):
        raw = ["P3", "P4"]
    return {str(level).strip().upper() for level in raw if str(level).strip().upper() in _LEVEL_RANK}


def _load_zvec() -> Any:
    try:
        import zvec  # type: ignore[import-not-found]
    except ImportError as exc:
        raise SemanticIndexError(
            "Zvec is not installed. Install the optional search dependencies: "
            "pip install -r requirements-semantic.txt"
        ) from exc
    return zvec


class HashingEmbedding:
    """Dependency-free deterministic embedding for tests and diagnostics only."""

    dimension = 128

    def embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        for token in re.findall(r"[\w가-힣]+", text.casefold()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dimension
            values[slot] += 1.0 if digest[4] & 1 else -1.0
        length = math.sqrt(sum(value * value for value in values))
        return [value / length for value in values] if length else values


class SentenceTransformerEmbedding:
    def __init__(self, model_name: str, device: str | None) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SemanticIndexError(
                "sentence-transformers is not installed. Install "
                "requirements-semantic.txt before enabling semantic search."
            ) from exc
        try:
            self._model = SentenceTransformer(model_name, device=device or None)
            self.dimension = int(self._model.get_sentence_embedding_dimension())
        except Exception as exc:
            raise SemanticIndexError(
                f"Could not load the local embedding model '{model_name}': {exc}"
            ) from exc

    def embed(self, text: str) -> list[float]:
        try:
            vector = self._model.encode(text, normalize_embeddings=True)
            return [float(value) for value in vector.tolist()]
        except Exception as exc:
            raise SemanticIndexError(f"Local embedding failed: {exc}") from exc


def _embedding_provider(config: dict[str, Any]) -> EmbeddingProvider:
    cfg = settings(config)
    provider = str(cfg.get("embedding_provider") or "sentence_transformers").strip().lower()
    if provider == "hashing":
        logger.warning("semantic_search.embedding_provider=hashing is test-only and not semantic")
        return HashingEmbedding()
    if provider != "sentence_transformers":
        raise SemanticIndexError(f"Unsupported local embedding provider: {provider}")
    model = str(cfg.get("embedding_model") or "intfloat/multilingual-e5-small").strip()
    device = str(cfg.get("embedding_device") or "cpu").strip() or None
    return SentenceTransformerEmbedding(model, device)


def chunk_text(text: str, config: dict[str, Any]) -> list[Chunk]:
    """Split extraction output at paragraph boundaries, retaining a stable anchor."""
    cfg = settings(config)
    max_chars = _int_setting(cfg, "chunk_max_chars", 1200, 200)
    max_chunks = _int_setting(cfg, "max_chunks_per_document", 80, 1)
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not blocks:
        blocks = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[Chunk] = []
    current: list[str] = []
    current_size = 0
    start = 1
    paragraph = 0
    for block in blocks:
        paragraph += 1
        pieces = [block[i : i + max_chars] for i in range(0, len(block), max_chars)] or [block]
        for piece in pieces:
            add_size = len(piece) + (1 if current else 0)
            if current and current_size + add_size > max_chars:
                chunks.append(Chunk("\n".join(current), f"paragraph:{start}-{paragraph - 1}"))
                if len(chunks) >= max_chunks:
                    return chunks
                current = []
                current_size = 0
                start = paragraph
            current.append(piece)
            current_size += len(piece) + (1 if current_size else 0)
    if current and len(chunks) < max_chunks:
        chunks.append(Chunk("\n".join(current), f"paragraph:{start}-{paragraph}"))
    return chunks


def _manifest_path(root: str) -> str:
    return os.path.join(root, _MANIFEST_NAME)


def _load_manifest(root: str) -> dict[str, Any]:
    path = _manifest_path(root)
    if not os.path.isfile(path):
        return {"version": 1, "files": {}}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("files"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        logger.warning("Semantic index manifest is unreadable; rebuilding its mapping")
    return {"version": 1, "files": {}}


def _save_manifest(root: str, manifest: dict[str, Any]) -> None:
    os.makedirs(root, exist_ok=True)
    destination = _manifest_path(root)
    temporary = destination + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, destination)


def _collection(root: str, zvec: Any, dimension: int, *, create: bool) -> Any:
    collection_root = os.path.join(root, "zvec")
    if os.path.isdir(collection_root):
        return zvec.open(collection_root)
    if not create:
        raise SemanticIndexError("Semantic index has not been created yet")
    fields = [
        zvec.FieldSchema("content", zvec.DataType.STRING, index_param=zvec.FtsIndexParam()),
        zvec.FieldSchema("file_id", zvec.DataType.STRING),
        zvec.FieldSchema("path", zvec.DataType.STRING),
        zvec.FieldSchema("anchor", zvec.DataType.STRING),
        zvec.FieldSchema("security_level", zvec.DataType.STRING),
        zvec.FieldSchema("tags", zvec.DataType.STRING),
        zvec.FieldSchema("category_ids", zvec.DataType.STRING),
        zvec.FieldSchema("last_analyzed_utc", zvec.DataType.STRING),
        zvec.FieldSchema("sha256", zvec.DataType.STRING),
    ]
    schema = zvec.CollectionSchema(
        _COLLECTION_NAME,
        fields=fields,
        vectors=zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, dimension),
    )
    os.makedirs(root, exist_ok=True)
    return zvec.create_and_open(collection_root, schema)


def _chunk_id(file_id: str, digest: str, ordinal: int) -> str:
    raw = f"{file_id}\x00{digest}\x00{ordinal}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _delete_ids(collection: Any, ids: list[str]) -> None:
    if ids:
        collection.delete(ids)


def remove_file(config: dict[str, Any], path: str) -> bool:
    """Delete chunks for one file. Does nothing while the feature is disabled."""
    if not enabled(config):
        return False
    root = index_path(config)
    manifest = _load_manifest(root)
    files = manifest.setdefault("files", {})
    record = files.get(path)
    if not isinstance(record, dict):
        return False
    ids = [str(value) for value in record.get("chunk_ids", []) if value]
    try:
        zvec = _load_zvec()
        dimension = int(record.get("dimension") or 0)
        if dimension and os.path.isdir(os.path.join(root, "zvec")):
            _delete_ids(_collection(root, zvec, dimension, create=False), ids)
    except SemanticIndexError:
        raise
    except Exception as exc:
        raise SemanticIndexError(f"Could not remove semantic index chunks: {exc}") from exc
    files.pop(path, None)
    _save_manifest(root, manifest)
    return True


def upsert_file(
    config: dict[str, Any],
    *,
    path: str,
    text: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Replace the indexed chunks for one classified file, if policy permits."""
    if not enabled(config):
        return {"indexed": False, "reason": "disabled"}
    level = str(metadata.get("security_level") or "").upper()
    if level not in indexed_levels(config):
        removed = remove_file(config, path)
        return {"indexed": False, "reason": "security_policy", "removed": removed}
    file_id = str(metadata.get("file_id") or "").strip()
    digest = str(metadata.get("sha256") or "").strip()
    if not file_id or not digest:
        raise SemanticIndexError("Semantic indexing requires file_id and sha256")
    chunks = chunk_text(text, config)
    if not chunks:
        return {"indexed": False, "reason": "empty"}
    root = index_path(config)
    manifest = _load_manifest(root)
    existing = (manifest.get("files") or {}).get(path)
    if isinstance(existing, dict) and existing.get("sha256") == digest:
        return {"indexed": True, "reason": "unchanged", "chunks": len(existing.get("chunk_ids") or [])}
    provider = _embedding_provider(config)
    max_total = _int_setting(settings(config), "max_total_chunks", 5000, 1)
    current_total = sum(
        len(record.get("chunk_ids") or [])
        for record in (manifest.get("files") or {}).values()
        if isinstance(record, dict)
    )
    replacing = len(existing.get("chunk_ids") or []) if isinstance(existing, dict) else 0
    if current_total - replacing + len(chunks) > max_total:
        raise SemanticIndexError(
            f"Semantic index chunk limit ({max_total}) would be exceeded; "
            "raise semantic_search.max_total_chunks or remove old indexed files"
        )
    zvec = _load_zvec()
    collection = _collection(root, zvec, provider.dimension, create=True)
    if isinstance(existing, dict):
        _delete_ids(collection, [str(value) for value in existing.get("chunk_ids", []) if value])
    tags = ", ".join(str(value) for value in metadata.get("tags", []) if str(value).strip())
    categories = ", ".join(str(value) for value in metadata.get("category_ids", []) if str(value).strip())
    docs = []
    ids: list[str] = []
    for ordinal, chunk in enumerate(chunks):
        chunk_id = _chunk_id(file_id, digest, ordinal)
        ids.append(chunk_id)
        docs.append(
            zvec.Doc(
                id=chunk_id,
                vectors={"embedding": provider.embed(chunk.text)},
                fields={
                    "content": chunk.text,
                    "file_id": file_id,
                    "path": path,
                    "anchor": chunk.anchor,
                    "security_level": level,
                    "tags": tags,
                    "category_ids": categories,
                    "last_analyzed_utc": str(metadata.get("last_analyzed_utc") or ""),
                    "sha256": digest,
                },
            )
        )
    collection.insert(docs)
    files = manifest.setdefault("files", {})
    files[path] = {
        "sha256": digest,
        "file_id": file_id,
        "chunk_ids": ids,
        "dimension": provider.dimension,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    _save_manifest(root, manifest)
    return {"indexed": True, "chunks": len(ids), "reason": "updated"}


def _result_level_allowed(config: dict[str, Any], level: str) -> bool:
    raw = str(settings(config).get("max_security_level_for_result") or "P4").upper()
    cap = _LEVEL_RANK.get(raw, _LEVEL_RANK["P4"])
    return _LEVEL_RANK.get(level.upper(), 99) <= cap


def search(
    config: dict[str, Any],
    query: str,
    *,
    level: str = "",
    tag: str = "",
    category_id: str = "",
    since: str = "",
    until: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Run local FTS + vector search and return compact policy-filtered evidence."""
    if not enabled(config):
        raise SemanticIndexError("Semantic search is disabled by semantic_search.enabled")
    text = str(query or "").strip()
    if not text:
        raise SemanticIndexError("query is required")
    try:
        requested_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise SemanticIndexError("limit must be an integer") from exc
    if requested_limit < 1 or requested_limit > _MAX_RESULTS:
        raise SemanticIndexError(f"limit must be between 1 and {_MAX_RESULTS}")
    root = index_path(config)
    manifest = _load_manifest(root)
    if not (manifest.get("files") or {}):
        return {"ok": True, "match_count": 0, "results": [], "freshness": "empty"}
    dimensions = {int(record.get("dimension") or 0) for record in manifest["files"].values() if isinstance(record, dict)}
    dimensions.discard(0)
    if len(dimensions) != 1:
        raise SemanticIndexError("Semantic index has incompatible embedding dimensions; rebuild it")
    provider = _embedding_provider(config)
    dimension = dimensions.pop()
    if provider.dimension != dimension:
        raise SemanticIndexError("Embedding model changed; rebuild the semantic index")
    zvec = _load_zvec()
    collection = _collection(root, zvec, dimension, create=False)
    allowed_levels = [
        candidate
        for candidate in sorted(indexed_levels(config))
        if _result_level_allowed(config, candidate)
    ]
    requested_level = str(level or "").strip().upper()
    if requested_level:
        allowed_levels = [candidate for candidate in allowed_levels if candidate == requested_level]
    if not allowed_levels:
        return {"ok": True, "match_count": 0, "results": [], "freshness": "fresh", "search_route": "policy_blocked"}
    quoted_levels = ", ".join(f"'{candidate}'" for candidate in allowed_levels)
    filter_expression = f"security_level IN ({quoted_levels})"
    query_count = min(_MAX_RESULTS, requested_limit * 4)
    fts_query = zvec.Query(
        field_name="content",
        fts=zvec.Fts(query_string=text),
        param=zvec.FtsQueryParam(),
    )
    vector_query = zvec.Query(field_name="embedding", vector=provider.embed(text))
    try:
        hits = collection.query(
            queries=[fts_query, vector_query],
            topk=query_count,
            filter=filter_expression,
            reranker=zvec.RrfReRanker(),
        )
        route = "hybrid"
    except Exception as exc:
        logger.debug("FTS query failed; falling back to vector search: %s", exc)
        hits = collection.query(queries=vector_query, topk=query_count, filter=filter_expression)
        route = "vector"
    wanted_level = requested_level
    results: list[dict[str, Any]] = []
    for hit in hits:
        fields = dict(hit.fields or {})
        hit_level = str(fields.get("security_level") or "").upper()
        if hit_level not in indexed_levels(config) or not _result_level_allowed(config, hit_level):
            continue
        if wanted_level and hit_level != wanted_level:
            continue
        if tag and str(tag).casefold() not in str(fields.get("tags") or "").casefold():
            continue
        if category_id and str(category_id) not in str(fields.get("category_ids") or ""):
            continue
        day = str(fields.get("last_analyzed_utc") or "")[:10]
        if since and day and day < str(since)[:10]:
            continue
        if until and day and day > str(until)[:10]:
            continue
        content = str(fields.get("content") or "")
        excerpt_limit = _int_setting(settings(config), "max_result_chars", 360, 40)
        results.append(
            {
                "path": str(fields.get("path") or ""),
                "file_id": str(fields.get("file_id") or ""),
                "anchor": str(fields.get("anchor") or ""),
                "security_level": hit_level,
                "tags": [value.strip() for value in str(fields.get("tags") or "").split(",") if value.strip()],
                "category_ids": [value.strip() for value in str(fields.get("category_ids") or "").split(",") if value.strip()],
                "last_analyzed_utc": str(fields.get("last_analyzed_utc") or ""),
                "sha256_prefix": str(fields.get("sha256") or "")[:16],
                "excerpt": content[:excerpt_limit],
                "truncated": len(content) > excerpt_limit,
                "score": round(float(hit.score or 0.0), 6),
            }
        )
        if len(results) >= requested_limit:
            break
    return {"ok": True, "match_count": len(results), "results": results, "freshness": "fresh", "search_route": route}
