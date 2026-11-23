
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from modules.question_clustering.clustering_strategies import HDBSCANClustering, ThresholdGraphClustering
from modules.question_clustering.semantic_question_aggregator import (
    CustomSemanticQuestionAggregator,
    InvalidQuestionError,
    QuestionRecord,
)

BILINGUAL_DATASET = [
    {"id": "q001", "text": "Thầy giảng lại phần này được không ạ?", "timestamp": "2026-08-25T10:00:00Z"},
    {"id": "q002", "text": "Can you explain this part again?", "timestamp": "2026-08-25T10:00:05Z"},
    {"id": "q003", "text": "Deadlock là gì?", "timestamp": "2026-08-25T10:01:00Z"},
    {"id": "q004", "text": "What is deadlock?", "timestamp": "2026-08-25T10:01:10Z"},
    {"id": "q005", "text": "SQL JOIN hoạt động như thế nào?", "timestamp": "2026-08-25T10:02:00Z"},
    {"id": "q006", "text": "How does an SQL JOIN work?", "timestamp": "2026-08-25T10:02:15Z"},
    {"id": "q007", "text": "Transaction trong cơ sở dữ liệu là gì?", "timestamp": "2026-08-25T10:03:00Z"},
    {"id": "q008", "text": "What is a database transaction?", "timestamp": "2026-08-25T10:03:20Z"},
    {"id": "q009", "text": "Concurrency và parallelism khác nhau thế nào?", "timestamp": "2026-08-25T10:04:00Z"},
    {"id": "q010", "text": "What's the difference between concurrency and parallelism?", "timestamp": "2026-08-25T10:04:12Z"},
    {"id": "q011", "text": "Recursion là gì trong lập trình?", "timestamp": "2026-08-25T10:05:00Z"},
    {"id": "q012", "text": "What is recursion in programming?", "timestamp": "2026-08-25T10:05:09Z"},
    {"id": "q013", "text": "Thầy có thể nói chậm hơn không ạ?", "timestamp": "2026-08-25T10:06:00Z"},
    {"id": "q014", "text": "Could you slow down a bit please?", "timestamp": "2026-08-25T10:06:07Z"},
    {"id": "q015", "text": "Em không hiểu ví dụ vừa rồi.", "timestamp": "2026-08-25T10:07:00Z"},
]


def _bare_aggregator(strategy=None) -> CustomSemanticQuestionAggregator:
    """Construct without running __init__ (skips model loading) so
    validation/similarity/representative/ranking logic can be unit-tested
    in complete isolation. `_clustering_strategy` is set manually since
    __init__ never ran."""
    agg = CustomSemanticQuestionAggregator.__new__(CustomSemanticQuestionAggregator)
    agg._clustering_strategy = strategy or ThresholdGraphClustering(threshold=0.78)
    return agg


def _questions(ids_and_ts: list[tuple[str, datetime]]) -> list[QuestionRecord]:
    return [QuestionRecord(id=qid, text=f"text-{qid}", timestamp=ts) for qid, ts in ids_and_ts]


# ===========================================================================
# Tier 1a — input validation
# ===========================================================================

class TestValidation:
    def test_reject_empty_text(self):
        agg = _bare_aggregator()
        with pytest.raises(InvalidQuestionError):
            agg.parse_and_validate([{"id": "q1", "text": "   ", "timestamp": "2026-08-25T10:00:00Z"}])

    def test_reject_malformed_timestamp(self):
        agg = _bare_aggregator()
        with pytest.raises(InvalidQuestionError):
            agg.parse_and_validate([{"id": "q1", "text": "hello", "timestamp": "not-a-date"}])

    def test_reject_duplicate_ids(self):
        agg = _bare_aggregator()
        rec = {"id": "q1", "text": "hello", "timestamp": "2026-08-25T10:00:00Z"}
        with pytest.raises(InvalidQuestionError):
            agg.parse_and_validate([rec, dict(rec)])

    def test_accepts_z_suffix_and_offset_timestamps(self):
        agg = _bare_aggregator()
        parsed = agg.parse_and_validate(
            [
                {"id": "q1", "text": "hi", "timestamp": "2026-08-25T10:00:00Z"},
                {"id": "q2", "text": "hi2", "timestamp": "2026-08-25T10:00:00+07:00"},
            ]
        )
        assert len(parsed) == 2

    def test_empty_batch_is_valid(self):
        agg = _bare_aggregator()
        assert agg.parse_and_validate([]) == []


# ===========================================================================
# Tier 1b — representative (medoid) selection, section 23 requirement
# ===========================================================================

class TestRepresentativeUnit:
    def test_argmax_no_tie(self):
        agg = _bare_aggregator()
        S = np.array([
            [1.0, 0.9, 0.5],
            [0.9, 1.0, 0.4],
            [0.5, 0.4, 1.0],
        ])
        ts = datetime(2026, 8, 25, tzinfo=timezone.utc)
        questions = _questions([("a", ts), ("b", ts), ("c", ts)])
        rep_idx, mean_sim = agg.select_representative([0, 1, 2], S, questions)
        assert rep_idx == 0  # off-diag sums: 1.4, 1.3, 0.9
        assert mean_sim == pytest.approx((0.9 + 0.5 + 0.9 + 0.4 + 0.5 + 0.4) / 6)

    def test_tie_break_by_timestamp(self):
        agg = _bare_aggregator()
        S = np.array([
            [1.0, 0.6, 0.6],
            [0.6, 1.0, 0.9],
            [0.6, 0.9, 1.0],
        ])  # off-diag sums: 1.2, 1.5, 1.5 -> tie between idx1, idx2
        earlier = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
        later = datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)
        questions = _questions([("m", later), ("z", later), ("a", earlier)])
        rep_idx, _ = agg.select_representative([0, 1, 2], S, questions)
        assert rep_idx == 2  # earlier timestamp wins, despite 'z' < 'a' not applying

    def test_tie_break_by_id_when_timestamps_equal(self):
        agg = _bare_aggregator()
        S = np.array([
            [1.0, 0.6, 0.6],
            [0.6, 1.0, 0.9],
            [0.6, 0.9, 1.0],
        ])
        same_ts = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
        questions = _questions([("m", same_ts), ("zzz", same_ts), ("aaa", same_ts)])
        rep_idx, _ = agg.select_representative([0, 1, 2], S, questions)
        assert rep_idx == 2  # 'aaa' < 'zzz'

    def test_singleton(self):
        agg = _bare_aggregator()
        S = np.array([[1.0]])
        ts = datetime(2026, 8, 25, tzinfo=timezone.utc)
        questions = _questions([("only", ts)])
        rep_idx, mean_sim = agg.select_representative([0], S, questions)
        assert rep_idx == 0
        assert mean_sim == 1.0


# ===========================================================================
# Tier 1c — clustering strategies, run directly on synthetic S matrices
# ===========================================================================

class TestClusteringStrategies:
    def test_threshold_graph_n_zero(self):
        strat = ThresholdGraphClustering(threshold=0.78)
        assert strat.fit_predict(np.zeros((0, 0))) == []

    def test_threshold_graph_n_one(self):
        strat = ThresholdGraphClustering(threshold=0.78)
        assert strat.fit_predict(np.array([[1.0]])) == [[0]]

    def test_threshold_graph_isolated_nodes(self):
        strat = ThresholdGraphClustering(threshold=0.78)
        S = np.array([
            [1.0, 0.1, 0.2],
            [0.1, 1.0, 0.1],
            [0.2, 0.1, 1.0],
        ])
        assert sorted(strat.fit_predict(S)) == [[0], [1], [2]]

    def test_threshold_graph_all_one_cluster(self):
        strat = ThresholdGraphClustering(threshold=0.78)
        S = np.full((4, 4), 0.9)
        np.fill_diagonal(S, 1.0)
        assert strat.fit_predict(S) == [[0, 1, 2, 3]]

    def test_threshold_graph_chaining_effect(self):
        """Documented limitation: A-B and B-C linked, A-C is not, all
        three still merge via transitive closure."""
        strat = ThresholdGraphClustering(threshold=0.78)
        S = np.array([
            [1.00, 0.80, 0.30],
            [0.80, 1.00, 0.80],
            [0.30, 0.80, 1.00],
        ])
        components = strat.fit_predict(S)
        assert components == [[0, 1, 2]]
        assert S[0, 2] < 0.78

    def test_threshold_graph_invalid_threshold(self):
        with pytest.raises(ValueError):
            ThresholdGraphClustering(threshold=0.0)
        with pytest.raises(ValueError):
            ThresholdGraphClustering(threshold=1.5)

    def test_hdbscan_n_zero_and_n_one(self):
        strat = HDBSCANClustering(min_cluster_size=2)
        assert strat.fit_predict(np.zeros((0, 0))) == []
        assert strat.fit_predict(np.array([[1.0]])) == [[0]]

    def test_hdbscan_noise_becomes_singleton_not_dropped(self):
        """Two tight pairs + one clear outlier: outlier must appear in the
        output as its own cluster, never silently dropped."""
        strat = HDBSCANClustering(min_cluster_size=2)
        S = np.array([
            [1.00, 0.95, 0.05, 0.05, 0.02],
            [0.95, 1.00, 0.05, 0.05, 0.02],
            [0.05, 0.05, 1.00, 0.95, 0.02],
            [0.05, 0.05, 0.95, 1.00, 0.02],
            [0.02, 0.02, 0.02, 0.02, 1.00],
        ])
        components = strat.fit_predict(S)
        all_indices = sorted(i for c in components for i in c)
        assert all_indices == [0, 1, 2, 3, 4]  # nobody dropped
        outlier_cluster = [c for c in components if 4 in c]
        assert outlier_cluster == [[4]]  # outlier is its own singleton

    def test_hdbscan_invalid_min_cluster_size(self):
        with pytest.raises(ValueError):
            HDBSCANClustering(min_cluster_size=1)


# ===========================================================================
# Tier 2 — baseline vs proposed, executed on synthetic structure
# ===========================================================================

class TestStrategyComparison:
    """[EXPERIMENTAL RESULT — synthetic structure only]. Builds a
    similarity matrix with a KNOWN ground truth (3 tight groups of 3 +
    1 lone outlier) and runs both strategies on it for real. This is a
    genuine, executed comparison — but on synthetic data with an
    intentionally easy structure. It demonstrates the plug-in
    architecture works and gives a first data point, NOT a validated
    answer to RQ2/RQ3 (which requires real question data + human
    judgment per the evaluation protocol in section 16)."""

    def _synthetic_similarity(self) -> np.ndarray:
        n = 10
        S = np.full((n, n), 0.05)
        groups = [[0, 1, 2], [3, 4, 5], [6, 7, 8]]  # index 9 = outlier
        for group in groups:
            for i in group:
                for j in group:
                    S[i, j] = 0.92
        np.fill_diagonal(S, 1.0)
        return S

    def test_both_strategies_recover_known_groups(self):
        S = self._synthetic_similarity()
        baseline = HDBSCANClustering(min_cluster_size=2).fit_predict(S)
        proposed = ThresholdGraphClustering(threshold=0.78).fit_predict(S)

        def as_sorted_sets(components):
            return sorted(sorted(c) for c in components)

        expected = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9]]
        assert as_sorted_sets(proposed) == expected
        assert as_sorted_sets(baseline) == expected
        # On this easy, well-separated synthetic structure both methods
        # agree completely — this synthetic case is not designed to be
        # discriminating; it only confirms neither strategy is broken.


# ===========================================================================
# Tier 1d — bilingual canonicalization format, Giai đoạn 1 (see
# Grouping_Quality_Summary_Overview.docx / evaluate_canonicalization_
# formats.py): a controlled pilot found the symmetric format
# "{text}. {translation}" beats the old asymmetric one on ARI/F1/recall at
# threshold=0.78 with no precision cost. This locks the exact format in with
# a stub translator, independent of the real NLLB model.
# ===========================================================================

class _StubTranslator:
    """[TEST DOUBLE] Satisfies the BilingualTranslator protocol without
    calling NLLB. `translations` maps (text, src_lang, tgt_lang) -> result;
    an unmapped key returns "" (mirrors a translator that fails silently)."""

    def __init__(self, translations: dict | None = None, raise_error: bool = False):
        self._translations = translations or {}
        self._raise_error = raise_error

    def detect_language(self, text: str) -> str:
        return "vi" if any(ch in text for ch in "ăâêôơưđạ") else "en"

    def transcript_text(self, text: str, src_lang: str, tgt_lang: str) -> str:
        if self._raise_error:
            raise RuntimeError("translation service unavailable")
        return self._translations.get((text, src_lang, tgt_lang), "")


class TestBilingualCanonicalization:
    def test_symmetric_format_vi_to_en(self):
        agg = _bare_aggregator()
        agg._translator = _StubTranslator({("Deadlock là gì ạ?", "vi", "en"): "What is deadlock?"})
        assert agg._to_bilingual_text("Deadlock là gì ạ?") == "Deadlock là gì ạ?. What is deadlock?"

    def test_symmetric_format_en_to_vi(self):
        agg = _bare_aggregator()
        agg._translator = _StubTranslator({("What is deadlock?", "en", "vi"): "Deadlock là gì?"})
        assert agg._to_bilingual_text("What is deadlock?") == "What is deadlock?. Deadlock là gì?"

    def test_no_translator_returns_original_text(self):
        agg = _bare_aggregator()
        agg._translator = None
        assert agg._to_bilingual_text("hello") == "hello"

    def test_empty_translation_falls_back_to_original(self):
        agg = _bare_aggregator()
        agg._translator = _StubTranslator({})
        assert agg._to_bilingual_text("What is deadlock?") == "What is deadlock?"

    def test_translation_error_falls_back_to_original(self):
        agg = _bare_aggregator()
        agg._translator = _StubTranslator(raise_error=True)
        assert agg._to_bilingual_text("What is deadlock?") == "What is deadlock?"


# ===========================================================================
# Tier 3 — API integration with a stub embedding backend
# (stub_model_module / api_client fixtures now live in tests/conftest.py)
# ===========================================================================

class TestAPIIntegration:
    def test_healthz(self, api_client):
        resp = api_client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_aggregate_happy_path(self, api_client):
        payload = {"questions": BILINGUAL_DATASET}
        resp = api_client.post("/api/v1/questions/aggregate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["metrics"]["total_questions"] == 15
        assert body["clustering_strategy"] == "threshold_graph_proposed"
        assert "timing_breakdown_ms" in body

    def test_aggregate_empty_list(self, api_client):
        resp = api_client.post("/api/v1/questions/aggregate", json={"questions": []})
        assert resp.status_code == 200
        assert resp.json()["clusters"] == []

    def test_aggregate_duplicate_ids_returns_422(self, api_client):
        payload = {"questions": [BILINGUAL_DATASET[0], BILINGUAL_DATASET[0]]}
        resp = api_client.post("/api/v1/questions/aggregate", json=payload)
        assert resp.status_code == 422
        assert "duplicate" in resp.json()["detail"].lower()

    def test_aggregate_empty_text_returns_422(self, api_client):
        payload = {"questions": [{"id": "q1", "text": "   ", "timestamp": "2026-08-25T10:00:00Z"}]}
        resp = api_client.post("/api/v1/questions/aggregate", json=payload)
        assert resp.status_code == 422

    def test_aggregate_missing_field_returns_422(self, api_client):
        # Pydantic shape validation catches this before it reaches the service.
        payload = {"questions": [{"id": "q1", "text": "hello"}]}
        resp = api_client.post("/api/v1/questions/aggregate", json=payload)
        assert resp.status_code == 422


# ===========================================================================
# Tier 4 — real end-to-end with the real multilingual model
# ===========================================================================

@pytest.fixture(scope="module")
def real_aggregator():
    try:
        return CustomSemanticQuestionAggregator()
    except RuntimeError as exc:
        pytest.skip(f"Real embedding model unavailable in this environment: {exc}")


class TestRealEndToEnd:
    def test_single_question(self, real_aggregator):
        result = real_aggregator.aggregate([BILINGUAL_DATASET[0]])
        assert len(result["clusters"]) == 1

    def test_expected_semantic_grouping(self, real_aggregator):
        result = real_aggregator.aggregate(BILINGUAL_DATASET)
        cluster_of = {}
        for cluster in result["clusters"]:
            for q in cluster["questions"]:
                cluster_of[q["id"]] = cluster["cluster_id"]
        assert cluster_of["q003"] == cluster_of["q004"]  # EN/VI deadlock pair

    def test_deterministic_ordering(self, real_aggregator):
        a = real_aggregator.aggregate(BILINGUAL_DATASET)
        b = real_aggregator.aggregate(BILINGUAL_DATASET)
        ids_a = [c["representative_id"] for c in a["clusters"]]
        ids_b = [c["representative_id"] for c in b["clusters"]]
        assert ids_a == ids_b

    @pytest.mark.parametrize("n", [10, 50, 100])
    def test_benchmark(self, real_aggregator, n):
        questions = []
        for i in range(n):
            src = BILINGUAL_DATASET[i % len(BILINGUAL_DATASET)]
            questions.append(
                {"id": f"bench-{i:04d}", "text": src["text"], "timestamp": f"2026-08-25T10:{i % 60:02d}:00Z"}
            )
        result = real_aggregator.aggregate(questions)
        print(f"\nN={n} timing_breakdown_ms={result['timing_breakdown_ms']}")
        assert result["execution_time_ms"] > 0


class TestConfusableTopicSeparation:
    """[REGRESSION — see Grouping_Quality_Summary_Overview.docx, muc 6/7]
    A controlled-simulation pilot (88 questions, 20 topics, real embedding
    model, threshold=0.78, no translator) measured pairwise Precision=1.000
    for ThresholdGraphClustering: no two distinct topics were ever merged
    into the same cluster, even the closest/most confusable pairs in the
    dataset. This test locks THAT property (precision / no false merge) in
    as a regression guard.

    It deliberately does NOT assert that a same-topic EN/VI pair must
    always merge — the same pilot measured pairwise recall of only 0.642 at
    this threshold without the translator step, i.e. some genuine
    same-topic cross-lingual pairs are known not to merge reliably. An
    earlier version of this test asserted that and failed on the isolated
    "polymorphism" EN/VI pair (which does not merge on its own) — a real
    finding, not a bug in this test, so the assertion was removed rather
    than the failure being papered over."""

    def test_concurrency_parallelism_and_process_thread_never_merge(self, real_aggregator):
        questions = [
            {"id": "a1", "text": "What's the difference between concurrency and parallelism?", "timestamp": "2026-08-25T10:00:00Z"},
            {"id": "a2", "text": "Concurrency và parallelism khác nhau thế nào ạ?", "timestamp": "2026-08-25T10:00:05Z"},
            {"id": "b1", "text": "What is the difference between a process and a thread?", "timestamp": "2026-08-25T10:01:00Z"},
            {"id": "b2", "text": "Process và thread khác nhau như thế nào ạ?", "timestamp": "2026-08-25T10:01:05Z"},
        ]
        result = real_aggregator.aggregate(questions)
        cluster_of = {q["id"]: c["cluster_id"] for c in result["clusters"] for q in c["questions"]}
        assert cluster_of["a1"] != cluster_of["b1"]
        assert cluster_of["a2"] != cluster_of["b2"]

    def test_oop_inheritance_and_polymorphism_never_merge(self, real_aggregator):
        questions = [
            {"id": "c1", "text": "What is inheritance in object-oriented programming?", "timestamp": "2026-08-25T10:00:00Z"},
            {"id": "c2", "text": "Kế thừa (inheritance) trong lập trình hướng đối tượng là gì ạ?", "timestamp": "2026-08-25T10:00:05Z"},
            {"id": "d1", "text": "What is polymorphism in object-oriented programming?", "timestamp": "2026-08-25T10:01:00Z"},
            {"id": "d2", "text": "Tính đa hình (polymorphism) trong OOP là gì ạ?", "timestamp": "2026-08-25T10:01:05Z"},
        ]
        result = real_aggregator.aggregate(questions)
        cluster_of = {q["id"]: c["cluster_id"] for c in result["clusters"] for q in c["questions"]}
        assert cluster_of["c1"] != cluster_of["d1"]
        assert cluster_of["c2"] != cluster_of["d2"]