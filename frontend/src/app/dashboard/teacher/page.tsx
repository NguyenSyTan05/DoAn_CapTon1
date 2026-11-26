"use client";

import { aiFetch } from "../../../lib/ai";
import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import styles from "./dashboard_teacher.module.css";

// [CUSTOM] Bảng dịch giao diện Dashboard Giảng viên — VN/EN. Gộp thẳng vào
// đây (không tách file translations.ts riêng) theo yêu cầu — sửa panel và
// sửa chữ ở cùng 1 file, không phải nhảy qua lại.
// Không dịch nội dung câu hỏi/câu trả lời của người dùng (dữ liệu thật,
// giữ nguyên ngôn ngữ gốc) — chỉ dịch nhãn/chữ tĩnh của giao diện.
type Language = "en" | "vi";

const translations = {
  en: {
    sidebarInstructorPlatform: "Instructor Platform",
    navWorkspace: "WORKSPACE",
    navOverview: "Overview",
    navQuestions: "Questions",
    navAiTopics: "AI Topics",
    navAnalytics: "Analytics",
    navSystem: "SYSTEM",
    navSettings: "Settings",
    aiEngineOnline: "AI Engine Online",
    semanticAnalysisActive: "Semantic analysis active",
    backToClassroom: "← Back to Classroom",

    breadcrumbWorkspace: "Workspace",
    breadcrumbAnalytics: "Question Analytics",
    pageTitle: "Question Analytics",
    pageDescription:
      "Monitor student questions and let AI organize them into meaningful topics.",
    aiDetailsBtn: "AI Details",
    refreshBtn: "Refresh Data",
    processingBtn: "Processing...",

    processingFailed: "AI processing failed",

    kpiTotalQuestions: "Total Questions",
    kpiTotalQuestionsDesc: "Student questions collected",
    kpiAiTopics: "AI Topics",
    kpiAiTopicsDesc: "Semantically grouped topics",
    kpiNeedsAttention: "Needs Attention",
    kpiNeedsAttentionDesc: "Topics waiting for an answer",
    kpiGroupingQuality: "AI Grouping Quality",

    topicsPanelTitle: "Question Topics",
    topicsPanelDesc: "AI-ranked semantic clusters from your classroom",
    topicsCount: (n: number) => `${n} topics`,
    searchPlaceholder: "Search questions or topics...",
    clearSearch: "Clear Search",

    emptyNoMatch: "No matching questions",
    emptyNoQuestions: "No questions yet",
    emptyTryAnother: "Try another search term.",
    emptyWillAppear:
      "Student questions will automatically appear here after they are submitted.",

    questionsBadge: (n: number) => `${n} questions`,
    answeredBadge: "Answered",
    pendingBadge: "Needs answer",
    similarityLabel: "Similarity",
    studentQuestionsLabel: (n: number) => `${n} student questions`,

    viewQuestions: "View questions",
    removeTopic: "Remove topic",

    studentQuestionsInTopic: "Student questions in this topic",
    relatedQuestions: (n: number) => `${n} related questions`,
    sentToQA: "✓ Sent to Q&A",
    answerPlaceholder: "Type your answer here...",
    sendToQA: "Send to Q&A",
    removeFromQA: "Remove from Q&A",
    questionIdLabel: (id: string) => `Question ID: ${id}`,

    aiInsights: "AI INSIGHTS",
    sessionOverview: "Session Overview",
    mostDiscussedTopic: "Most discussed topic",
    needsAttentionLabel: "Needs attention",
    topicsUnanswered: (n: number) => `${n} topics unanswered`,
    percentCompleted: (pct: number) => `${pct}% of topics completed`,
    aiGroupingConfidence: "Grouping confidence",
    percentSimilarity: (pct: string) => `${pct}% similarity`,
    semanticClustering: "Semantic clustering",
    insightsWillAppear: "AI insights will appear after questions are processed.",

    avgClusterSize: "Average cluster size",
    largestClusterLabel: "Largest cluster",
    singletonTopics: "Singleton topics",
    compressionRatio: "Compression ratio",

    aiEngine: "AI ENGINE",
    processingDetails: "Processing Details",
    clusteringStrategy: "Clustering Strategy",
    translationLabel: "Translation",
    embeddingLabel: "Embedding",
    similarityTimeLabel: "Similarity",
    clusteringLabel: "Clustering",
    representativeLabel: "Representative",
    serializationLabel: "Serialization",
    totalProcessingLabel: "Total Processing",

    checkingPermissions: "Checking instructor permissions...",

    onlyTeacherAlert: "Only teacher accounts can access this dashboard.",
    removeTopicConfirm: (n: number) =>
      `Remove this topic and its ${n} questions?`,

    settingsTitle: "Settings",
    languageLabel: "Language",

    translateBtn: "Translate",
    translatingBtn: "Translating...",
    showOriginalBtn: "Show original",
    translateFailed: "Translation failed — please try again.",

    slideEngagementTitle: "Slide Engagement",
    slideEngagementDesc: "Questions asked while each slide was shown",
    slideLabel: (n: number) => `Slide ${n}`,
    noSlideData: "No slide data yet — upload slides in the classroom to see this.",
  },
  vi: {
    sidebarInstructorPlatform: "Nền tảng Giảng viên",
    navWorkspace: "KHÔNG GIAN LÀM VIỆC",
    navOverview: "Tổng quan",
    navQuestions: "Câu hỏi",
    navAiTopics: "Chủ đề AI",
    navAnalytics: "Phân tích",
    navSystem: "HỆ THỐNG",
    navSettings: "Cài đặt",
    aiEngineOnline: "AI đang hoạt động",
    semanticAnalysisActive: "Đang phân tích ngữ nghĩa",
    backToClassroom: "← Quay lại lớp học",

    breadcrumbWorkspace: "Không gian làm việc",
    breadcrumbAnalytics: "Phân tích câu hỏi",
    pageTitle: "Phân tích câu hỏi",
    pageDescription:
      "Theo dõi câu hỏi của sinh viên và để AI tự động gom nhóm theo chủ đề.",
    aiDetailsBtn: "Chi tiết AI",
    refreshBtn: "Làm mới dữ liệu",
    processingBtn: "Đang xử lý...",

    processingFailed: "Xử lý AI thất bại",

    kpiTotalQuestions: "Tổng số câu hỏi",
    kpiTotalQuestionsDesc: "Câu hỏi đã thu thập từ sinh viên",
    kpiAiTopics: "Chủ đề AI",
    kpiAiTopicsDesc: "Chủ đề đã gom nhóm theo ngữ nghĩa",
    kpiNeedsAttention: "Cần chú ý",
    kpiNeedsAttentionDesc: "Chủ đề đang chờ trả lời",
    kpiGroupingQuality: "Chất lượng gom nhóm AI",

    topicsPanelTitle: "Chủ đề câu hỏi",
    topicsPanelDesc: "Cụm ngữ nghĩa được AI xếp hạng từ lớp học của bạn",
    topicsCount: (n: number) => `${n} chủ đề`,
    searchPlaceholder: "Tìm câu hỏi hoặc chủ đề...",
    clearSearch: "Xoá tìm kiếm",

    emptyNoMatch: "Không tìm thấy câu hỏi phù hợp",
    emptyNoQuestions: "Chưa có câu hỏi nào",
    emptyTryAnother: "Hãy thử từ khoá khác.",
    emptyWillAppear:
      "Câu hỏi của sinh viên sẽ tự động hiện ở đây sau khi được gửi.",

    questionsBadge: (n: number) => `${n} câu hỏi`,
    answeredBadge: "Đã trả lời",
    pendingBadge: "Cần trả lời",
    similarityLabel: "Độ tương đồng",
    studentQuestionsLabel: (n: number) => `${n} câu hỏi sinh viên`,

    viewQuestions: "Xem câu hỏi",
    removeTopic: "Xoá chủ đề",

    studentQuestionsInTopic: "Câu hỏi sinh viên trong chủ đề này",
    relatedQuestions: (n: number) => `${n} câu hỏi liên quan`,
    sentToQA: "✓ Đã gửi tới Q&A",
    answerPlaceholder: "Nhập câu trả lời của bạn...",
    sendToQA: "Gửi tới Q&A",
    removeFromQA: "Gỡ khỏi Q&A",
    questionIdLabel: (id: string) => `Mã câu hỏi: ${id}`,

    aiInsights: "THÔNG TIN AI",
    sessionOverview: "Tổng quan phiên học",
    mostDiscussedTopic: "Chủ đề được hỏi nhiều nhất",
    needsAttentionLabel: "Cần chú ý",
    topicsUnanswered: (n: number) => `${n} chủ đề chưa trả lời`,
    percentCompleted: (pct: number) => `${pct}% chủ đề đã hoàn thành`,
    aiGroupingConfidence: "Độ tin cậy",
    percentSimilarity: (pct: string) => `${pct}% tương đồng`,
    semanticClustering: "Gom cụm ngữ nghĩa",
    insightsWillAppear: "Thông tin AI sẽ hiện sau khi câu hỏi được xử lý.",

    avgClusterSize: "Kích thước cụm trung bình",
    largestClusterLabel: "Cụm lớn nhất",
    singletonTopics: "Chủ đề đơn lẻ",
    compressionRatio: "Tỉ lệ nén",

    aiEngine: "BỘ MÁY AI",
    processingDetails: "Chi tiết xử lý",
    clusteringStrategy: "Chiến lược gom cụm",
    translationLabel: "Dịch",
    embeddingLabel: "Embedding",
    similarityTimeLabel: "Độ tương đồng",
    clusteringLabel: "Gom cụm",
    representativeLabel: "Chọn đại diện",
    serializationLabel: "Đóng gói",
    totalProcessingLabel: "Tổng thời gian xử lý",

    checkingPermissions: "Đang kiểm tra quyền giảng viên...",

    onlyTeacherAlert: "Chỉ tài khoản giảng viên mới truy cập được Dashboard này.",
    removeTopicConfirm: (n: number) =>
      `Xoá chủ đề này và ${n} câu hỏi liên quan?`,

    settingsTitle: "Cài đặt",
    languageLabel: "Ngôn ngữ",

    translateBtn: "Dịch",
    translatingBtn: "Đang dịch...",
    showOriginalBtn: "Xem bản gốc",
    translateFailed: "Dịch thất bại — vui lòng thử lại.",

    slideEngagementTitle: "Mức độ tương tác theo slide",
    slideEngagementDesc: "Số câu hỏi được gửi trong lúc mỗi slide đang hiển thị",
    slideLabel: (n: number) => `Slide ${n}`,
    noSlideData: "Chưa có dữ liệu slide — hãy upload slide trong phòng học để xem mục này.",
  },
} as const;

interface QuestionInput {
  id: string;
  text: string;
  timestamp: string;
}

interface QuestionEcho {
  id: string;
  text: string;
}

interface ClusterOutput {
  cluster_id: number;
  representative_id: string;
  representative_text: string;
  total_count: number;
  mean_similarity: number;
  questions: QuestionEcho[];
}

interface MetricsOutput {
  total_questions: number;
  total_clusters: number;
  average_cluster_size: number;
  largest_cluster_size: number;
  singleton_clusters: number;
  mean_intra_cluster_similarity: number;
}

interface TimingBreakdownOutput {
  translation_time_ms: number;
  embedding_time_ms: number;
  similarity_time_ms: number;
  clustering_time_ms: number;
  representative_time_ms: number;
  serialization_time_ms: number;
  total_processing_time_ms: number;
}

interface AggregateResponse {
  clusters: ClusterOutput[];
  compression_ratio: number;
  execution_time_ms: number;
  timing_breakdown_ms: TimingBreakdownOutput;
  clustering_strategy: string;
  metrics: MetricsOutput;
}

interface AnswerOutput {
  representative_id: string;
  representative_text: string;
  total_count: number;
  answer_text: string;
  answered_at: string;
}

interface SlideEngagementItem {
  slide_number: number;
  question_count: number;
}

// [PHẦN 1] aiFetch() (lib/ai.ts) tự gắn ?session=<id> của phiên đang mở (mở dashboard từ /room hoặc
// /dashboard/teacher?session=<id>) để câu hỏi/câu trả lời/slide tách theo phiên, kèm JWT.

export default function TeacherDashboard() {
  const router = useRouter();

  const [isAuthorized, setIsAuthorized] = useState(false);
  const [data, setData] = useState<AggregateResponse | null>(null);
  const [totalStoredCount, setTotalStoredCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [expandedClusterId, setExpandedClusterId] = useState<number | null>(
    null,
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, AnswerOutput>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [searchTerm, setSearchTerm] = useState("");
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<number | null>(null);

  // [CUSTOM] Dịch câu đại diện theo yêu cầu (on-demand) — giảng viên chỉ
  // đọc tiếng Anh, câu hỏi có thể là tiếng Việt. Dùng lại NLLB đã có qua
  // POST /api/v1/translate (không dịch từng câu thành viên, chỉ câu đại
  // diện — theo đúng phạm vi đã thống nhất).
  const [clusterTranslations, setClusterTranslations] = useState<
    Record<string, string>
  >({});
  const [showTranslated, setShowTranslated] = useState<Record<string, boolean>>(
    {},
  );
  const [translatingId, setTranslatingId] = useState<string | null>(null);

  // [CUSTOM] Toggle ngôn ngữ giao diện Dashboard VN/EN — lưu lại lựa chọn
  // trong localStorage để nhớ giữa các lần mở lại (dữ liệu người dùng gửi
  // — câu hỏi/câu trả lời — KHÔNG bị dịch, chỉ dịch nhãn giao diện tĩnh).
  const [language, setLanguage] = useState<Language>("en");
  const [showSettings, setShowSettings] = useState(false);
  const t = translations[language];

  useEffect(() => {
    const saved = localStorage.getItem("dashboard_language");
    if (saved === "en" || saved === "vi") {
      const timer = window.setTimeout(() => setLanguage(saved), 0);
      return () => window.clearTimeout(timer);
    }
  }, []);

  const changeLanguage = (lang: Language) => {
    setLanguage(lang);
    localStorage.setItem("dashboard_language", lang);
  };

  /* =========================================================
     ANSWERS — nguồn thật từ backend (be/service/answer_store.py),
     KHÔNG còn lưu boolean ảo trong localStorage như trước. Xem
     Grouping_Quality_Summary_Overview.docx cho lý do kiến trúc này.
  ========================================================= */

  const fetchAnswers = useCallback(async () => {
    try {
      const res = await aiFetch(`/api/v1/answers`);
      if (!res.ok) return;
      const data = await res.json();
      const map: Record<string, AnswerOutput> = {};
      for (const a of data.answers ?? []) map[a.representative_id] = a;
      setAnswers(map);
    } catch (error) {
      console.error("Cannot fetch answers:", error);
    }
  }, []);

  /* =========================================================
     SLIDE ENGAGEMENT — đối chiếu timestamp câu hỏi với timestamp
     chuyển slide (SlideViewer.tsx), tính ở backend
     (be/service/slide_store.py: compute_engagement).
  ========================================================= */

  const [slideEngagement, setSlideEngagement] = useState<SlideEngagementItem[]>([]);

  const fetchSlideEngagement = useCallback(async () => {
    try {
      const res = await aiFetch(`/api/v1/slides/engagement`);
      if (!res.ok) return;
      const data = await res.json();
      setSlideEngagement(data.slides ?? []);
    } catch (error) {
      console.error("Cannot fetch slide engagement:", error);
    }
  }, []);

  const translateRepresentative = async (cluster: ClusterOutput) => {
    const id = cluster.representative_id;

    // Đã dịch rồi → chỉ toggle ẩn/hiện, không gọi lại NLLB
    if (showTranslated[id]) {
      setShowTranslated((prev) => ({ ...prev, [id]: false }));
      return;
    }
    if (clusterTranslations[id]) {
      setShowTranslated((prev) => ({ ...prev, [id]: true }));
      return;
    }

    setTranslatingId(id);
    try {
      const res = await aiFetch(`/api/v1/translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: cluster.representative_text }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const result = await res.json();

      setClusterTranslations((prev) => ({ ...prev, [id]: result.translated_text }));
      setShowTranslated((prev) => ({ ...prev, [id]: true }));
    } catch (error) {
      console.error("Cannot translate:", error);
      alert(t.translateFailed);
    } finally {
      setTranslatingId(null);
    }
  };

  const submitAnswer = async (cluster: ClusterOutput) => {
    const text = (drafts[cluster.representative_id] ?? "").trim();
    if (!text) return;

    try {
      await aiFetch(`/api/v1/answers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          representative_id: cluster.representative_id,
          representative_text: cluster.representative_text,
          total_count: cluster.total_count,
          answer_text: text,
        }),
      });
      setDrafts((prev) => ({ ...prev, [cluster.representative_id]: "" }));
      await fetchAnswers();
    } catch (error) {
      console.error("Cannot submit answer:", error);
    }
  };

  const removeAnswer = async (representativeId: string) => {
    try {
      await aiFetch(`/api/v1/answers/${representativeId}`, {
        method: "DELETE",
      });
      await fetchAnswers();
    } catch (error) {
      console.error("Cannot remove answer:", error);
    }
  };

  /* =========================================================
     FETCH CLUSTERS
  ========================================================= */

  const fetchClusters = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);

    // [SỬA] Lấy câu hỏi từ kho chung phía server (GET /api/v1/questions)
    // thay vì chỉ đọc localStorage của riêng trình duyệt này — để câu hỏi
    // sinh viên gửi từ THIẾT BỊ KHÁC cũng xuất hiện ở đây. localStorage
    // "room_questions" vẫn được ghi ở nơi khác (không xoá) nhưng không
    // còn là nguồn đọc chính nữa.
    let questionsPayload: QuestionInput[] = [];

    try {
      const questionsRes = await aiFetch(`/api/v1/questions`);
      if (questionsRes.ok) {
        const questionsData = await questionsRes.json();
        questionsPayload = questionsData.questions ?? [];
      }
    } catch (error) {
      console.error("Cannot fetch questions:", error);
    }

    setTotalStoredCount(questionsPayload.length);

    if (questionsPayload.length === 0) {
      setData(null);
      setLoading(false);
      return;
    }

    try {
      const response = await aiFetch(`/api/v1/questions/aggregate`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            questions: questionsPayload,
          }),
        },
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `Server error: ${response.status}`);
      }

      const result: AggregateResponse = await response.json();

      setData(result);
      await fetchAnswers();
      await fetchSlideEngagement();
    } catch (error: unknown) {
      console.error("Aggregation API error:", error);

      setErrorMessage(
        error instanceof Error && error.message
          ? error.message
          : "Unable to connect to the AI backend.",
      );
    } finally {
      setLoading(false);
    }
  }, [fetchAnswers, fetchSlideEngagement]);

  /* =========================================================
     AUTHORIZATION
  ========================================================= */

  useEffect(() => {
    let role: string | undefined;
    try {
      const stored = JSON.parse(localStorage.getItem("user") || "null");
      role = typeof stored?.role === "string" ? stored.role : undefined;
    } catch {
      role = undefined;
    }
    const token = localStorage.getItem("token");

    if (!token || !role) {
      router.push("/login");
      return;
    }

    if (!["giang_vien", "lecturer", "teacher"].includes(role)) {
      alert(t.onlyTeacherAlert);
      router.push("/");
      return;
    }

    const timer = window.setTimeout(() => {
      setIsAuthorized(true);
      void fetchClusters();
    }, 0);
    return () => window.clearTimeout(timer);
    // t.onlyTeacherAlert cố tình không đưa vào deps — effect này chỉ nên
    // chạy 1 lần lúc mount, không nên chạy lại mỗi khi đổi ngôn ngữ.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router, fetchClusters]);

  /* =========================================================
     DELETE CLUSTER
  ========================================================= */

  const removeCluster = async (cluster: ClusterOutput) => {
    const confirmed = window.confirm(t.removeTopicConfirm(cluster.total_count));

    if (!confirmed) return;

    try {
      const idsToRemove = new Set(
        cluster.questions.map((question) => question.id),
      );

      // [GIỮ NGUYÊN — không xoá theo yêu cầu] dọn cache localStorage cục
      // bộ nếu có (best-effort — không dừng hàm nếu rỗng, vì câu hỏi có
      // thể đến từ THIẾT BỊ KHÁC và chưa từng nằm trong localStorage của
      // trình duyệt này).
      const rawSaved = localStorage.getItem("room_questions");
      if (rawSaved) {
        const savedQuestions: QuestionInput[] = JSON.parse(rawSaved);
        const remainingQuestions = savedQuestions.filter(
          (question) => !idsToRemove.has(question.id),
        );
        localStorage.setItem(
          "room_questions",
          JSON.stringify(remainingQuestions),
        );
      }

      // [SỬA — thật sự cần thiết] Xoá từng câu hỏi khỏi QuestionStore phía
      // server — nếu không, GET /api/v1/questions ở lần fetch kế tiếp vẫn
      // trả về các câu này (server không biết gì về việc xoá cục bộ ở
      // trên), khiến topic vừa "xoá" lại hồi sinh ngay sau khi refresh.
      await Promise.all(
        Array.from(idsToRemove).map((id) =>
          aiFetch(`/api/v1/questions/${id}`, { method: "DELETE" }),
        ),
      );

      // [BUG FIX — đã làm trước đó] Xoá topic trước đây chỉ xoá câu hỏi khỏi room_questions —
      // nếu cụm này đã được trả lời, câu trả lời vẫn nằm nguyên trong
      // answer_store trên backend và tiếp tục hiện ở mọi tab Q&A (vì không
      // có gì báo cho backend xoá). Gọi luôn DELETE /api/v1/answers để nó
      // biến mất khỏi Q&A qua broadcast, đồng bộ với việc xoá topic.
      if (answers[cluster.representative_id]) {
        await removeAnswer(cluster.representative_id);
      }

      setOpenMenuId(null);
      setExpandedClusterId(null);

      await fetchClusters();
    } catch (error) {
      console.error("Delete cluster error:", error);
    }
  };

  /* =========================================================
     FILTER CLUSTERS
  ========================================================= */

  const filteredClusters = useMemo(() => {
    if (!data?.clusters) return [];

    const keyword = searchTerm.toLowerCase().trim();

    if (!keyword) {
      return data.clusters;
    }

    return data.clusters.filter((cluster) => {
      const representativeMatch = cluster.representative_text
        .toLowerCase()
        .includes(keyword);

      const questionMatch = cluster.questions.some((question) =>
        question.text.toLowerCase().includes(keyword),
      );

      return representativeMatch || questionMatch;
    });
  }, [data, searchTerm]);

  /* =========================================================
     DASHBOARD METRICS
  ========================================================= */

  const unansweredClusters = useMemo(() => {
    if (!data) return 0;

    return data.clusters.filter(
      (cluster) => !answers[cluster.representative_id],
    ).length;
  }, [data, answers]);

  const largestCluster = useMemo(() => {
    if (!data?.clusters.length) return null;

    return [...data.clusters].sort((a, b) => b.total_count - a.total_count)[0];
  }, [data]);

  const answeredPercentage = useMemo(() => {
    if (!data?.clusters.length) return 0;

    return Math.round(
      ((data.clusters.length - unansweredClusters) / data.clusters.length) *
        100,
    );
  }, [data, unansweredClusters]);

  /* =========================================================
     LOADING
  ========================================================= */

  if (!isAuthorized) {
    return (
      <div className={styles.loadingScreen}>
        <div className={styles.loadingSpinner} />
        <p>{t.checkingPermissions}</p>
      </div>
    );
  }

  return (
    <div className={styles.dashboard}>
      {/* =====================================================
          SIDEBAR
      ===================================================== */}

      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <div className={styles.brandIcon}>AI</div>

          <div>
            <h2>Classroom AI</h2>
            <span>{t.sidebarInstructorPlatform}</span>
          </div>
        </div>

        <nav className={styles.navigation}>
          <div className={styles.navSectionTitle}>{t.navWorkspace}</div>

          <button
            className={`${styles.navItem} ${styles.navItemActive}`}
            onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          >
            <span className={styles.navIcon}>▦</span>
            {t.navOverview}
          </button>

          <button
            className={styles.navItem}
            onClick={() => {
              setSearchTerm("");
              document.getElementById("topics")?.scrollIntoView({ behavior: "smooth" });
            }}
          >
            <span className={styles.navIcon}>?</span>
            {t.navQuestions}
            <span className={styles.navCount}>
              {data?.metrics.total_questions ?? totalStoredCount}
            </span>
          </button>

          <button
            className={styles.navItem}
            onClick={() =>
              document.getElementById("topics")?.scrollIntoView({ behavior: "smooth" })
            }
          >
            <span className={styles.navIcon}>◈</span>
            {t.navAiTopics}
            <span className={styles.navCount}>
              {data?.metrics.total_clusters ?? 0}
            </span>
          </button>

          <button
            className={styles.navItem}
            onClick={() =>
              document.getElementById("slide-analytics")?.scrollIntoView({ behavior: "smooth" })
            }
          >
            <span className={styles.navIcon}>▥</span>
            {t.navAnalytics}
          </button>

          <div className={styles.navDivider} />

          <div className={styles.navSectionTitle}>{t.navSystem}</div>

          <button className={styles.navItem} onClick={() => setShowSettings(true)}>
            <span className={styles.navIcon}>⚙</span>
            {t.navSettings}
          </button>
        </nav>

        <div className={styles.sidebarBottom}>
          <div className={styles.aiStatus}>
            <span className={styles.statusDot} />

            <div>
              <strong>{t.aiEngineOnline}</strong>
              <span>{t.semanticAnalysisActive}</span>
            </div>
          </div>

          <button
            className={styles.backClassroom}
            onClick={() => router.push("/")}
          >
            {t.backToClassroom}
          </button>
        </div>
      </aside>

      {/* =====================================================
          MAIN
      ===================================================== */}

      <main className={styles.main}>
        {/* HEADER */}

        <header className={styles.topbar}>
          <div>
            <div className={styles.breadcrumb}>
              {t.breadcrumbWorkspace} <span>/</span> {t.breadcrumbAnalytics}
            </div>

            <h1>{t.pageTitle}</h1>

            <p>{t.pageDescription}</p>
          </div>

          <div className={styles.headerActions}>
            <button
              className={styles.secondaryButton}
              onClick={() => setShowTechnicalDetails(true)}
            >
              <span>⌘</span>
              {t.aiDetailsBtn}
            </button>

            <button
              className={styles.primaryButton}
              onClick={fetchClusters}
              disabled={loading}
            >
              <span>{loading ? "↻" : "↻"}</span>
              {loading ? t.processingBtn : t.refreshBtn}
            </button>
          </div>
        </header>

        {/* ERROR */}

        {errorMessage && (
          <div className={styles.errorBanner}>
            <div className={styles.errorIcon}>!</div>

            <div>
              <strong>{t.processingFailed}</strong>
              <p>{errorMessage}</p>
            </div>

            <button onClick={() => setErrorMessage(null)}>×</button>
          </div>
        )}

        {/* =====================================================
            KPI CARDS
        ===================================================== */}

        <section className={styles.metricsGrid}>
          <div className={styles.metricCard}>
            <div className={styles.metricTop}>
              <span>{t.kpiTotalQuestions}</span>
              <div className={`${styles.metricIcon} ${styles.blue}`}>?</div>
            </div>

            <div className={styles.metricValue}>
              {data?.metrics.total_questions ?? totalStoredCount}
            </div>

            <div className={styles.metricDescription}>
              {t.kpiTotalQuestionsDesc}
            </div>
          </div>

          <div className={styles.metricCard}>
            <div className={styles.metricTop}>
              <span>{t.kpiAiTopics}</span>
              <div className={`${styles.metricIcon} ${styles.purple}`}>◈</div>
            </div>

            <div className={styles.metricValue}>
              {data?.metrics.total_clusters ?? 0}
            </div>

            <div className={styles.metricDescription}>
              {t.kpiAiTopicsDesc}
            </div>
          </div>

          <div className={styles.metricCard}>
            <div className={styles.metricTop}>
              <span>{t.kpiNeedsAttention}</span>
              <div className={`${styles.metricIcon} ${styles.orange}`}>!</div>
            </div>

            <div className={styles.metricValue}>{unansweredClusters}</div>

            <div className={styles.metricDescription}>
              {t.kpiNeedsAttentionDesc}
            </div>
          </div>

          <div className={styles.metricCard}>
            <div className={styles.metricTop}>
              <span>{t.kpiGroupingQuality}</span>
              <div className={`${styles.metricIcon} ${styles.green}`}>✓</div>
            </div>

            <div className={styles.metricValue}>
              {data
                ? `${(data.metrics.mean_intra_cluster_similarity * 100).toFixed(
                    1,
                  )}%`
                : "0%"}
            </div>

            <div className={styles.progressTrack}>
              <div
                className={styles.progressBar}
                style={{
                  width: data
                    ? `${Math.min(
                        data.metrics.mean_intra_cluster_similarity * 100,
                        100,
                      )}%`
                    : "0%",
                }}
              />
            </div>
          </div>
        </section>

        {/* =====================================================
            CONTENT GRID
        ===================================================== */}

        <section id="topics" className={styles.contentGrid}>
          {/* TOPICS */}

          <div className={styles.topicsPanel}>
            <div className={styles.panelHeader}>
              <div>
                <h2>{t.topicsPanelTitle}</h2>
                <p>{t.topicsPanelDesc}</p>
              </div>

              <div className={styles.topicCount}>
                {t.topicsCount(filteredClusters.length)}
              </div>
            </div>

            <div className={styles.toolbar}>
              <div className={styles.searchBox}>
                <span>⌕</span>

                <input
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                  placeholder={t.searchPlaceholder}
                />

                {searchTerm && (
                  <button
                    onClick={() => setSearchTerm("")}
                    className={styles.clearSearch}
                  >
                    ×
                  </button>
                )}
              </div>
            </div>

            {/* EMPTY */}

            {(!data || filteredClusters.length === 0) && (
              <div className={styles.emptyState}>
                <div className={styles.emptyIcon}>?</div>

                <h3>
                  {searchTerm ? t.emptyNoMatch : t.emptyNoQuestions}
                </h3>

                <p>
                  {searchTerm ? t.emptyTryAnother : t.emptyWillAppear}
                </p>

                {searchTerm && (
                  <button
                    className={styles.secondaryButton}
                    onClick={() => setSearchTerm("")}
                  >
                    {t.clearSearch}
                  </button>
                )}
              </div>
            )}

            {/* CLUSTERS */}

            <div className={styles.clusterList}>
              {filteredClusters.map((cluster, index) => {
                const isExpanded = expandedClusterId === cluster.cluster_id;

                const answer = answers[cluster.representative_id];
                const isAnswered = Boolean(answer);

                const similarity = cluster.mean_similarity * 100;

                return (
                  <article
                    key={cluster.cluster_id}
                    className={`${styles.clusterCard} ${
                      isExpanded ? styles.clusterExpanded : ""
                    }`}
                  >
                    <div
                      className={styles.clusterHeader}
                      onClick={() => {
                        setExpandedClusterId(isExpanded ? null : cluster.cluster_id);
                      }}
                    >
                      <div className={styles.rank}>#{index + 1}</div>

                      <div className={styles.clusterMain}>
                        <div className={styles.clusterMetaTop}>
                          <span className={styles.topicBadge}>
                            {t.questionsBadge(cluster.total_count)}
                          </span>

                          <span
                            className={
                              isAnswered
                                ? styles.answeredBadge
                                : styles.pendingBadge
                            }
                          >
                            <span />
                            {isAnswered ? t.answeredBadge : t.pendingBadge}
                          </span>
                        </div>

                        <div className={styles.representativeRow}>
                          <h3>
                            {showTranslated[cluster.representative_id] &&
                            clusterTranslations[cluster.representative_id]
                              ? clusterTranslations[cluster.representative_id]
                              : cluster.representative_text}
                          </h3>

                          <button
                            type="button"
                            className={styles.translateBtn}
                            disabled={translatingId === cluster.representative_id}
                            onClick={(event) => {
                              event.stopPropagation();
                              translateRepresentative(cluster);
                            }}
                          >
                            {translatingId === cluster.representative_id
                              ? t.translatingBtn
                              : showTranslated[cluster.representative_id]
                                ? t.showOriginalBtn
                                : t.translateBtn}
                          </button>
                        </div>

                        <div className={styles.clusterStats}>
                          <span>
                            {t.similarityLabel} <strong>{similarity.toFixed(0)}%</strong>
                          </span>

                          <span className={styles.statSeparator}>•</span>

                          <span>
                            {t.studentQuestionsLabel(cluster.questions.length)}
                          </span>
                        </div>
                      </div>

                      <div className={styles.clusterActions}>
                        <div
                          className={styles.menuWrapper}
                          onClick={(event) => event.stopPropagation()}
                        >
                          <button
                            className={styles.moreButton}
                            onClick={() =>
                              setOpenMenuId(
                                openMenuId === cluster.cluster_id
                                  ? null
                                  : cluster.cluster_id,
                              )
                            }
                          >
                            ⋮
                          </button>

                          {openMenuId === cluster.cluster_id && (
                            <div className={styles.actionMenu}>
                              <button
                                onClick={() => {
                                  setExpandedClusterId(cluster.cluster_id);
                                  setOpenMenuId(null);
                                }}
                              >
                                {t.viewQuestions}
                              </button>

                              <button
                                className={styles.deleteAction}
                                onClick={() => removeCluster(cluster)}
                              >
                                {t.removeTopic}
                              </button>
                            </div>
                          )}
                        </div>

                        <button className={styles.expandButton}>
                          {isExpanded ? "⌃" : "⌄"}
                        </button>
                      </div>
                    </div>

                    {/* EXPANDED */}

                    {isExpanded && (
                      <div className={styles.clusterDetails}>
                        <div className={styles.detailHeader}>
                          <div>
                            <strong>{t.studentQuestionsInTopic}</strong>

                            <span>
                              {t.relatedQuestions(cluster.questions.length)}
                            </span>
                          </div>

                          {isAnswered && (
                            <span className={styles.answerButtonDone}>
                              {t.sentToQA}
                            </span>
                          )}
                        </div>

                        {/* ANSWER — gửi thật qua /api/v1/answers, đẩy
                            real-time tới sinh viên qua WebSocket */}
                        {answer ? (
                          <div className={styles.answerPublished}>
                            <p>{answer.answer_text}</p>
                            <button
                              className={styles.answerRemoveBtn}
                              onClick={() =>
                                removeAnswer(cluster.representative_id)
                              }
                            >
                              {t.removeFromQA}
                            </button>
                          </div>
                        ) : (
                          <div className={styles.answerBox}>
                            <textarea
                              className={styles.answerTextarea}
                              value={drafts[cluster.representative_id] ?? ""}
                              onChange={(e) =>
                                setDrafts((prev) => ({
                                  ...prev,
                                  [cluster.representative_id]: e.target.value,
                                }))
                              }
                              placeholder={t.answerPlaceholder}
                            />
                            <button
                              className={styles.answerSendBtn}
                              disabled={
                                !(drafts[cluster.representative_id] ?? "").trim()
                              }
                              onClick={() => submitAnswer(cluster)}
                            >
                              {t.sendToQA}
                            </button>
                          </div>
                        )}

                        <div className={styles.questionList}>
                          {cluster.questions.map((question, questionIndex) => (
                            <div
                              className={styles.questionItem}
                              key={question.id}
                            >
                              <div className={styles.questionNumber}>
                                {questionIndex + 1}
                              </div>

                              <div className={styles.questionContent}>
                                <p>{question.text}</p>

                                <span>{t.questionIdLabel(question.id)}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </div>

          {/* ===================================================
              AI INSIGHTS
          =================================================== */}

          <aside className={styles.insightsPanel}>
            <div className={styles.insightsHeader}>
              <div>
                <h2>{t.sessionOverview}</h2>
              </div>
            </div>

            {largestCluster ? (
              <>
                <div className={styles.insightCard}>
                  <div className={`${styles.insightIcon} ${styles.fire}`}>
                    ↑
                  </div>

                  <div>
                    <span>{t.mostDiscussedTopic}</span>

                    <strong>{largestCluster.representative_text}</strong>

                    <small>{t.questionsBadge(largestCluster.total_count)}</small>
                  </div>
                </div>

                <div className={styles.insightCard}>
                  <div className={`${styles.insightIcon} ${styles.warning}`}>
                    !
                  </div>

                  <div>
                    <span>{t.needsAttentionLabel}</span>

                    <strong>{t.topicsUnanswered(unansweredClusters)}</strong>

                    <small>{t.percentCompleted(answeredPercentage)}</small>
                  </div>
                </div>

                <div className={styles.insightCard}>
                  <div className={`${styles.insightIcon} ${styles.success}`}>
                    ✓
                  </div>

                  <div>
                    <span>{t.aiGroupingConfidence}</span>

                    <strong>
                      {data
                        ? t.percentSimilarity(
                            (
                              data.metrics.mean_intra_cluster_similarity * 100
                            ).toFixed(1),
                          )
                        : "—"}
                    </strong>
                  </div>
                </div>
              </>
            ) : (
              <div className={styles.noInsights}>
                <div>✦</div>
                <p>{t.insightsWillAppear}</p>
              </div>
            )}
            {/* SLIDE ENGAGEMENT — đối chiếu timestamp câu hỏi với timestamp
                chuyển slide (SlideViewer.tsx), tính sẵn ở backend */}
            <div id="slide-analytics" className={styles.slideChart}>
              <div className={styles.slideChartHeader}>
                <h3>{t.slideEngagementTitle}</h3>
                <p>{t.slideEngagementDesc}</p>
              </div>

              {slideEngagement.length === 0 ? (
                <div className={styles.slideChartEmpty}>{t.noSlideData}</div>
              ) : (
                (() => {
                  const maxCount = Math.max(
                    ...slideEngagement.map((s) => s.question_count),
                  );
                  return slideEngagement.map((slide) => (
                    <div key={slide.slide_number} className={styles.slideBarRow}>
                      <span className={styles.slideBarLabel}>
                        {t.slideLabel(slide.slide_number)}
                      </span>
                      <div className={styles.slideBarTrack}>
                        <div
                          className={styles.slideBarFill}
                          style={{
                            width: `${(slide.question_count / maxCount) * 100}%`,
                          }}
                        />
                      </div>
                      <span className={styles.slideBarCount}>
                        {slide.question_count}
                      </span>
                    </div>
                  ));
                })()
              )}
            </div>
          </aside>
        </section>
      </main>

      {/* =====================================================
          AI TECHNICAL MODAL
      ===================================================== */}

      {showTechnicalDetails && data && (
        <div
          className={styles.modalOverlay}
          onClick={() => setShowTechnicalDetails(false)}
        >
          <div
            className={styles.modal}
            onClick={(event) => event.stopPropagation()}
          >
            <div className={styles.modalHeader}>
              <div>
                <span className={styles.aiLabel}>
                  <span>✦</span>
                  {t.aiEngine}
                </span>

                <h2>{t.processingDetails}</h2>
              </div>

              <button
                className={styles.modalClose}
                onClick={() => setShowTechnicalDetails(false)}
              >
                ×
              </button>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.algorithmBox}>
                <span>{t.clusteringStrategy}</span>
                <strong>{data.clustering_strategy}</strong>
              </div>

              <div className={styles.timingGrid}>
                <div>
                  <span>{t.translationLabel}</span>
                  <strong>
                    {data.timing_breakdown_ms.translation_time_ms} ms
                  </strong>
                </div>

                <div>
                  <span>{t.embeddingLabel}</span>
                  <strong>
                    {data.timing_breakdown_ms.embedding_time_ms} ms
                  </strong>
                </div>

                <div>
                  <span>{t.similarityTimeLabel}</span>
                  <strong>
                    {data.timing_breakdown_ms.similarity_time_ms} ms
                  </strong>
                </div>

                <div>
                  <span>{t.clusteringLabel}</span>
                  <strong>
                    {data.timing_breakdown_ms.clustering_time_ms} ms
                  </strong>
                </div>

                <div>
                  <span>{t.representativeLabel}</span>
                  <strong>
                    {data.timing_breakdown_ms.representative_time_ms} ms
                  </strong>
                </div>

                <div>
                  <span>{t.serializationLabel}</span>
                  <strong>
                    {data.timing_breakdown_ms.serialization_time_ms} ms
                  </strong>
                </div>

                <div className={styles.totalTiming}>
                  <span>{t.totalProcessingLabel}</span>
                  <strong>
                    {data.timing_breakdown_ms.total_processing_time_ms ||
                      data.execution_time_ms}{" "}
                    ms
                  </strong>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* =====================================================
          SETTINGS MODAL — chuyển ngôn ngữ giao diện VN/EN
      ===================================================== */}

      {showSettings && (
        <div
          className={styles.modalOverlay}
          onClick={() => setShowSettings(false)}
        >
          <div
            className={styles.modal}
            onClick={(event) => event.stopPropagation()}
          >
            <div className={styles.modalHeader}>
              <div>
                <span className={styles.aiLabel}>
                  <span>⚙</span>
                  {t.settingsTitle}
                </span>

                <h2>{t.settingsTitle}</h2>
              </div>

              <button
                className={styles.modalClose}
                onClick={() => setShowSettings(false)}
              >
                ×
              </button>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.settingRow}>
                <span className={styles.settingLabel}>{t.languageLabel}</span>

                <div className={styles.langToggle}>
                  <button
                    className={`${styles.langOption} ${
                      language === "en" ? styles.langOptionActive : ""
                    }`}
                    onClick={() => changeLanguage("en")}
                  >
                    EN
                  </button>
                  <button
                    className={`${styles.langOption} ${
                      language === "vi" ? styles.langOptionActive : ""
                    }`}
                    onClick={() => changeLanguage("vi")}
                  >
                    VN
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
