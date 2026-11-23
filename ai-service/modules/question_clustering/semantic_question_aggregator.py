
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine_similarity

from modules.question_clustering.clustering_strategies import ClusteringStrategy, ThresholdGraphClustering

logger = logging.getLogger("classbridge.semantic_question_aggregator")


@runtime_checkable
class BilingualTranslator(Protocol):

    def detect_language(self, text: str) -> str: ...
    def transcript_text(self, text: str, src_lang: str, tgt_lang: str) -> str: ...


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InvalidQuestionError(ValueError):
    """Raised when one or more input question records fail validation.
    [DESIGN DECISION] the whole batch is rejected with every problem
    listed — no record is silently skipped or auto-normalized. In a
    classroom setting, a silently-dropped question is a silenced student.
    """


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QuestionRecord:
    id: str
    text: str
    timestamp: datetime


@dataclass
class ClusterResult:
    cluster_id: int
    member_indices: list[int]
    representative_index: int
    mean_similarity: float


@dataclass
class TimingBreakdown:
    """Wall-clock ms per stage. Excludes model loading / startup / CUDA
    warm-up, which are one-time costs, not per-request cost."""
    translation_ms: float = 0.0
    embedding_ms: float = 0.0
    similarity_ms: float = 0.0
    clustering_ms: float = 0.0
    representative_ms: float = 0.0
    serialization_ms: float = 0.0

    @property
    def total_ms(self) -> float:
        return (
            self.translation_ms
            + self.embedding_ms
            + self.similarity_ms
            + self.clustering_ms
            + self.representative_ms
            + self.serialization_ms
        )

    def as_dict(self) -> dict:
        return {
            "translation_time_ms": round(self.translation_ms, 3),
            "embedding_time_ms": round(self.embedding_ms, 3),
            "similarity_time_ms": round(self.similarity_ms, 3),
            "clustering_time_ms": round(self.clustering_ms, 3),
            "representative_time_ms": round(self.representative_ms, 3),
            "serialization_time_ms": round(self.serialization_ms, 3),
            "total_processing_time_ms": round(self.total_ms, 3),
        }


# ---------------------------------------------------------------------------
# Main service class
# ---------------------------------------------------------------------------

class CustomSemanticQuestionAggregator:

    _EPS = 1e-9
    DEFAULT_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        device: Optional[str] = None,
        batch_size: int = 32,
        clustering_strategy: Optional[ClusteringStrategy] = None,
        translator: Optional[BilingualTranslator] = None,
    ) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._device = device or self._select_device()
        self._translator = translator
        # [DESIGN DECISION] default = proposed method (threshold graph,
        # default threshold 0.78). Swap this at construction time to run
        # the HDBSCAN baseline instead, for comparison experiments.
        self._clustering_strategy: ClusteringStrategy = (
            clustering_strategy or ThresholdGraphClustering(threshold=0.78)
        )
        # [DESIGN DECISION — Giai đoạn 2 optimization] main.py's dashboard
        # re-POSTs the FULL question list on every "Refresh" (stateless,
        # full-batch API — see architecture.md). Without this cache, every
        # already-processed question would be re-translated and re-encoded
        # on every refresh, even though embedding is the most expensive
        # stage (see TimingBreakdown). Keyed by question id, storing the
        # exact text it was computed from so a (hypothetical, currently
        # unsupported) edited question can't silently reuse a stale vector.
        # Grows unboundedly for the lifetime of this instance — acceptable
        # for a single classroom session's question volume; not meant for
        # a long-lived multi-session server process.
        self._embedding_cache: dict[str, tuple[str, np.ndarray]] = {}

        logger.info(
            "Loading embedding model '%s' on device '%s' (clustering strategy: %s)...",
            model_name, self._device, self._clustering_strategy.name,
        )
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. Install it to use "
                "CustomSemanticQuestionAggregator (`pip install sentence-transformers`)."
            ) from exc

        try:
            self._model = SentenceTransformer(model_name, device=self._device)
        except Exception as exc:  # noqa: BLE001 - deliberately surface any load failure
            logger.error("Failed to load embedding model '%s': %s", model_name, exc)
            raise RuntimeError(
                f"Embedding model initialization failed for '{model_name}': {exc}"
            ) from exc

        self._embedding_dim = self._model.get_sentence_embedding_dimension()
        logger.info(
            "Model loaded on '%s'. Embedding dimension: %d", self._device, self._embedding_dim
        )

    @staticmethod
    def _select_device() -> str:
        """[EXISTING LIBRARY: torch] CUDA if available, else CPU. Never raises."""
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
        return "cpu"

    @property
    def clustering_strategy_name(self) -> str:
        return self._clustering_strategy.name

    # ------------------------------------------------------------------
    # Input validation [CUSTOM IMPLEMENTATION] — framework-independent
    # ------------------------------------------------------------------

    def parse_and_validate(self, raw_questions: list[dict]) -> list[QuestionRecord]:
        if not isinstance(raw_questions, list):
            raise InvalidQuestionError("Input must be a list of question records.")

        seen_ids: set[str] = set()
        duplicate_ids: set[str] = set()
        parsed: list[QuestionRecord] = []
        errors: list[str] = []

        for idx, raw in enumerate(raw_questions):
            if not isinstance(raw, dict):
                errors.append(f"[index {idx}] record is not an object")
                continue

            qid = raw.get("id")
            text = raw.get("text")
            ts_raw = raw.get("timestamp")

            if not qid or not isinstance(qid, str):
                errors.append(f"[index {idx}] missing or invalid 'id'")
                continue
            if qid in seen_ids:
                duplicate_ids.add(qid)
            seen_ids.add(qid)

            if text is None or not isinstance(text, str) or not text.strip():
                errors.append(f"[index {idx}, id={qid}] 'text' is empty or whitespace-only")
                continue

            try:
                ts = self._parse_timestamp(ts_raw)
            except (ValueError, TypeError) as exc:
                errors.append(f"[index {idx}, id={qid}] malformed timestamp: {ts_raw!r} ({exc})")
                continue

            parsed.append(QuestionRecord(id=qid, text=text.strip(), timestamp=ts))

        if duplicate_ids:
            errors.append(f"duplicate question id(s) found: {sorted(duplicate_ids)}")
        if errors:
            raise InvalidQuestionError("Input validation failed:\n" + "\n".join(errors))

        return parsed

    @staticmethod
    def _parse_timestamp(value) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("timestamp must be a non-empty ISO-8601 string")
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # ------------------------------------------------------------------
    # Bilingual canonicalization [CUSTOM IMPLEMENTATION]
    # ------------------------------------------------------------------

    def _to_bilingual_text(self, text: str) -> str:
        """[DESIGN DECISION] Concatenation is symmetric regardless of source
        language ("{original}. {translation}") — an earlier asymmetric
        version (translation-first + no space for vi->en, original-first +
        comma for en->vi) measured lower pairwise recall in a controlled
        pilot (see Grouping_Quality_Summary_Overview.docx / evaluate_
        canonicalization_formats.py): ARI 0.644->0.682, F1 0.652->0.689 at
        threshold=0.78, with no precision cost. That pilot did NOT show
        canonicalization beating no-canonicalization outright — this fix
        only removes a strictly-dominated format, it does not resolve
        whether translation-based canonicalization helps overall."""
        if self._translator is None:
            return text
        try:
            lang = self._translator.detect_language(text)
            other_lang = "en" if lang == "vi" else "vi"
            translation = self._translator.transcript_text(text, lang, other_lang).strip()
            return f"{text}. {translation}" if translation else text
        except Exception:
            logger.warning(
                "Bilingual translation failed for a question; embedding original text only.",
                exc_info=True,
            )
            return text

    # ------------------------------------------------------------------
    # Embedding [EXISTING LIBRARY: sentence-transformers]
    # ------------------------------------------------------------------

    def encode_questions(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._embedding_dim), dtype=np.float32)
        embeddings = self._model.encode(
            texts,
            batch_size=self._batch_size,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=False,
        )
        return np.asarray(embeddings, dtype=np.float32)

    def normalize_embeddings(self, embeddings: np.ndarray) -> np.ndarray:
        if embeddings.size == 0:
            return embeddings
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        zero_mask = (norms < self._EPS).reshape(-1)
        safe_norms = np.where(norms < self._EPS, 1.0, norms)
        normalized = embeddings / safe_norms
        if np.any(zero_mask):
            logger.warning(
                "%d embedding(s) had ~zero norm; kept as zero-vectors (no NaN).",
                int(zero_mask.sum()),
            )
            normalized[zero_mask] = 0.0
        return normalized

    # ------------------------------------------------------------------
    # Similarity [EXISTING LIBRARY: scikit-learn]
    # ------------------------------------------------------------------

    def compute_similarity(self, normalized_embeddings: np.ndarray) -> np.ndarray:
        n = normalized_embeddings.shape[0]
        if n == 0:
            return np.zeros((0, 0), dtype=np.float32)
        S = sklearn_cosine_similarity(normalized_embeddings)
        np.clip(S, -1.0, 1.0, out=S)
        return S

    # ------------------------------------------------------------------
    # Clustering — delegated to the injected strategy
    # ------------------------------------------------------------------

    def cluster_questions(self, S: np.ndarray) -> list[list[int]]:
        return self._clustering_strategy.fit_predict(S)

    # ------------------------------------------------------------------
    # Representative (medoid) selection [CUSTOM IMPLEMENTATION of tie-break]
    # ------------------------------------------------------------------

    def select_representative(
        self,
        cluster_indices: list[int],
        S: np.ndarray,
        questions: list[QuestionRecord],
    ) -> tuple[int, float]:
        if len(cluster_indices) == 1:
            return cluster_indices[0], 1.0

        sub = S[np.ix_(cluster_indices, cluster_indices)]
        sums = sub.sum(axis=1) - np.diag(sub)

        max_sum = sums.max()
        tie_mask = np.isclose(sums, max_sum, atol=1e-9)
        candidates = [cluster_indices[i] for i in np.where(tie_mask)[0]]

        if len(candidates) > 1:
            candidates.sort(key=lambda idx: (questions[idx].timestamp, questions[idx].id))
        representative_index = candidates[0]

        n = len(cluster_indices)
        pair_count = n * (n - 1)
        off_diag_sum = float(sub.sum() - np.trace(sub))
        mean_similarity = off_diag_sum / pair_count if pair_count > 0 else 1.0

        return representative_index, mean_similarity

    # ------------------------------------------------------------------
    # Ranking [CUSTOM IMPLEMENTATION]
    # ------------------------------------------------------------------

    def rank_clusters(
        self, clusters: list[ClusterResult], questions: list[QuestionRecord]
    ) -> list[ClusterResult]:
        def sort_key(c: ClusterResult):
            rep_timestamp = questions[c.representative_index].timestamp
            return (-len(c.member_indices), -c.mean_similarity, rep_timestamp)

        return sorted(clusters, key=sort_key)

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def calculate_metrics(self, clusters: list[ClusterResult], n_questions: int) -> dict:
        if n_questions == 0:
            return {
                "total_questions": 0,
                "total_clusters": 0,
                "average_cluster_size": 0.0,
                "largest_cluster_size": 0,
                "singleton_clusters": 0,
                "mean_intra_cluster_similarity": 0.0,
            }
        n_clusters = len(clusters)
        sizes = [len(c.member_indices) for c in clusters]
        singleton_count = sum(1 for s in sizes if s == 1)
        mean_sim = float(np.mean([c.mean_similarity for c in clusters])) if clusters else 0.0
        return {
            "total_questions": n_questions,
            "total_clusters": n_clusters,
            "average_cluster_size": round(sum(sizes) / n_clusters, 4) if n_clusters else 0.0,
            "largest_cluster_size": max(sizes) if sizes else 0,
            "singleton_clusters": singleton_count,
            "mean_intra_cluster_similarity": round(mean_sim, 4),
        }

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def aggregate(self, raw_questions: list[dict]) -> dict:
        """Full pipeline: validate -> bilingual canonicalize -> encode ->
        normalize -> similarity -> cluster -> representative -> rank ->
        metrics -> response dict. Zero FastAPI/Pydantic dependency —
        callable directly from tests."""
        questions = self.parse_and_validate(raw_questions)
        n = len(questions)
        timing = TimingBreakdown()

        if n == 0:
            return self._build_response([], questions, 0, timing)

        # [Giai đoạn 2 optimization] Skip translation + encoding entirely
        # for any question whose id was already processed with the exact
        # same text — see _embedding_cache in __init__.
        t0 = time.perf_counter()
        uncached_indices: list[int] = []
        for i, q in enumerate(questions):
            cached = self._embedding_cache.get(q.id)
            if cached is None or cached[0] != q.text:
                uncached_indices.append(i)
        canonical_texts = [self._to_bilingual_text(questions[i].text) for i in uncached_indices]
        timing.translation_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        if canonical_texts:
            raw_embeddings = self.encode_questions(canonical_texts)
            new_embeddings = self.normalize_embeddings(raw_embeddings)
            for local_idx, i in enumerate(uncached_indices):
                self._embedding_cache[questions[i].id] = (questions[i].text, new_embeddings[local_idx])
        embeddings = np.stack([self._embedding_cache[q.id][1] for q in questions])
        timing.embedding_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        S = self.compute_similarity(embeddings)
        timing.similarity_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        components = self.cluster_questions(S)
        timing.clustering_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        clusters: list[ClusterResult] = []
        for component in components:
            rep_idx, mean_sim = self.select_representative(component, S, questions)
            clusters.append(
                ClusterResult(
                    cluster_id=-1,
                    member_indices=component,
                    representative_index=rep_idx,
                    mean_similarity=mean_sim,
                )
            )
        timing.representative_ms = (time.perf_counter() - t0) * 1000

        ranked = self.rank_clusters(clusters, questions)
        for new_id, cluster in enumerate(ranked, start=1):
            cluster.cluster_id = new_id

        t0 = time.perf_counter()
        response = self._build_response(ranked, questions, n, timing)
        timing.serialization_ms = (time.perf_counter() - t0) * 1000
        response["execution_time_ms"] = round(timing.total_ms, 3)
        response["timing_breakdown_ms"] = timing.as_dict()

        return response

    def _build_response(
        self,
        ranked_clusters: list[ClusterResult],
        questions: list[QuestionRecord],
        n_questions: int,
        timing: TimingBreakdown,
    ) -> dict:
        cluster_payload = []
        for c in ranked_clusters:
            rep = questions[c.representative_index]
            cluster_payload.append(
                {
                    "cluster_id": c.cluster_id,
                    "representative_id": rep.id,
                    "representative_text": rep.text,
                    "total_count": len(c.member_indices),
                    "mean_similarity": round(c.mean_similarity, 4),
                    "questions": [
                        {"id": questions[i].id, "text": questions[i].text}
                        for i in c.member_indices
                    ],
                }
            )

        n_clusters = len(ranked_clusters)
        compression_ratio = (n_clusters / n_questions) if n_questions > 0 else 0.0

        return {
            "clusters": cluster_payload,
            "compression_ratio": round(compression_ratio, 4),
            "execution_time_ms": round(timing.total_ms, 3),
            "timing_breakdown_ms": timing.as_dict(),
            "clustering_strategy": self._clustering_strategy.name,
            "metrics": self.calculate_metrics(ranked_clusters, n_questions),
        }