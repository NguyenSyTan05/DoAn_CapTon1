
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components as scipy_connected_components

logger = logging.getLogger("classbridge.clustering_strategies")


class ClusteringStrategy(ABC):
    name: str = "abstract"

    @abstractmethod
    def fit_predict(self, S: np.ndarray) -> list[list[int]]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# BASELINE — HDBSCAN
# ---------------------------------------------------------------------------

class HDBSCANClustering(ClusteringStrategy):
    name = "hdbscan_baseline"

    def __init__(self, min_cluster_size: int = 2, min_samples: Optional[int] = None):
        if min_cluster_size < 2:
            raise ValueError("min_cluster_size must be >= 2 (hdbscan library constraint)")
        self._min_cluster_size = min_cluster_size
        self._min_samples = min_samples

    def fit_predict(self, S: np.ndarray) -> list[list[int]]:
        n = S.shape[0]
        if n == 0:
            return []
        if n == 1:
            return [[0]]

        try:
            import hdbscan
        except ImportError as exc:
            raise RuntimeError(
                "hdbscan is not installed. Install it to use HDBSCANClustering "
                "(`pip install hdbscan`), or select the threshold-graph strategy instead."
            ) from exc

        # cosine distance = 1 - cosine similarity; clip for float safety.
        distance = np.clip(1.0 - S, 0.0, 2.0).astype(np.float64)
        np.fill_diagonal(distance, 0.0)  # self-distance must be exactly 0

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self._min_cluster_size,
            min_samples=self._min_samples,
            metric="precomputed",
        )
        labels = clusterer.fit_predict(distance)

        clusters: dict[int, list[int]] = {}
        next_singleton_id = -1
        for idx, label in enumerate(labels):
            if label == -1:
                # design decision: noise -> own singleton, not dropped
                clusters[next_singleton_id] = [idx]
                next_singleton_id -= 1
            else:
                clusters.setdefault(int(label), []).append(idx)

        return [sorted(members) for members in clusters.values()]
class ThresholdGraphClustering(ClusteringStrategy):
    name = "threshold_graph_proposed"

    def __init__(self, threshold: float = 0.75):
        if not (0.0 < threshold <= 1.0):
            raise ValueError(f"threshold must satisfy 0.0 < threshold <= 1.0, got {threshold}")
        self._threshold = threshold

    def fit_predict(self, S: np.ndarray) -> list[list[int]]:
        n = S.shape[0]
        if n == 0:
            return []
        if n == 1:
            return [[0]]

        adjacency = (S >= self._threshold).astype(np.int8)
        np.fill_diagonal(adjacency, 0)  # no self-loops
        sparse_adjacency = csr_matrix(adjacency)

        n_components, labels = scipy_connected_components(
            sparse_adjacency, directed=False, connection="weak"
        )

        clusters: dict[int, list[int]] = {}
        for idx, label in enumerate(labels):
            clusters.setdefault(int(label), []).append(idx)

        return [sorted(members) for members in clusters.values()]