"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  BookMarked,
  CheckCircle2,
  Copy,
  Edit3,
  FileText,
  Flame,
  Layers,
  Lightbulb,
  Printer,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";
import { aiFetch, currentSession } from "../../lib/ai";
import studentService from "../../services/student.service";
import styles from "./LessonSummaryPage.module.css";

type SessionOption = {
  id: string;
  title: string;
  status: string;
  startedAt: string | null;
  endedAt: string | null;
  classCode: string;
  className: string;
  lecturerName?: string;
};

type LectureSection = {
  section_index: number;
  title: string;
  time_range: string;
  summary_vi: string;
  summary_en: string;
  segment_count: number;
};

type KeyConceptItem = {
  concept: string;
  explanation_vi: string;
  explanation_en: string;
};

type VocabularyItem = {
  term_en: string;
  term_vi: string;
  definition_en: string;
  explanation_vi: string;
  example_text: string;
};

type ExampleItem = {
  timestamp: string;
  text_vi: string;
  text_en: string;
};

type ClarificationItem = {
  topic: string;
  question_count: number;
  status: "answered" | "pending";
  answer_text: string;
  recommendation: string;
};

type HeatmapSlideItem = {
  slide_number: number;
  question_count: number;
  heat_level: "low" | "medium" | "high" | "critical";
  intensity_pct: number;
};

type LessonSummaryRecord = {
  session_id: string;
  lesson_title: string;
  detected_subject: string;
  overview: string;
  overview_en: string;
  lecture_structure: LectureSection[];
  key_concepts: KeyConceptItem[];
  vocabulary: VocabularyItem[];
  examples: ExampleItem[];
  key_takeaways: string[];
  further_clarification: ClarificationItem[];
  heatmap: HeatmapSlideItem[];
  transcript_count: number;
  question_count: number;
  version_number: number;
  model_name: string;
  generation_status: "EMPTY" | "COMPLETED";
  updated_at: string;
};

type StudentNoteItem = {
  note_id: string;
  title: string;
  content: string;
  source_type: "PERSONAL" | "AI_COPY" | "LECTURER";
  is_pinned: boolean;
  updated_at: string;
};

export default function LessonSummaryPage({
  mode,
}: {
  mode: "lecturer" | "student";
}) {
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionOption[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string>("");
  const [summary, setSummary] = useState<LessonSummaryRecord | null>(null);
  const [notes, setNotes] = useState<StudentNoteItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [okMsg, setOkMsg] = useState("");

  // Chế độ giảng viên tạo/chỉnh sửa bản tóm tắt
  const [showGenForm, setShowGenForm] = useState(false);
  const [genTitle, setGenTitle] = useState("");
  const [genLecturerNotes, setGenLecturerNotes] = useState("");

  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editOverview, setEditOverview] = useState("");
  const [editTakeaways, setEditTakeaways] = useState("");

  // Ghi chú cá nhân & phản hồi buổi học
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [savingNote, setSavingNote] = useState(false);

  const [rating, setRating] = useState(5);
  const [feedbackComment, setFeedbackComment] = useState("");
  const [sendingFeedback, setSendingFeedback] = useState(false);

  const fetchSummaryAndNotes = useCallback(async (sid: string) => {
    if (!sid) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setErrorMsg("");
    try {
      const [sumRes, notesRes] = await Promise.all([
        aiFetch(`/api/v1/summaries?session=${encodeURIComponent(sid)}`),
        aiFetch(`/api/v1/summaries/notes?session=${encodeURIComponent(sid)}`),
      ]);
      if (!sumRes.ok) {
        const body = await sumRes.json().catch(() => ({}));
        const rawDetail = body?.detail;
        const msg =
          typeof rawDetail === "string"
            ? rawDetail
            : rawDetail?.code === "session_closed"
              ? "Phiên học này đã bị huỷ."
              : rawDetail?.code === "session_forbidden"
                ? "Bạn không có quyền truy cập bản tóm tắt của phiên học này."
                : `Không thể tải bản tóm tắt (HTTP ${sumRes.status}).`;
        throw new Error(msg);
      }
      const sumData: LessonSummaryRecord = await sumRes.json();
      setSummary(sumData);
      setEditTitle(sumData.lesson_title);
      setEditOverview(sumData.overview);
      setEditTakeaways(sumData.key_takeaways.join("\n"));

      if (notesRes.ok) {
        const notesData = await notesRes.json();
        setNotes(notesData.notes ?? []);
      }
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Không kết nối được dịch vụ AI (cổng 8000).",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const urlSession = currentSession() || "";
    studentService
      .getSummarySessions()
      .then((list: SessionOption[]) => {
        if (!active) return;
        setSessions(list);
        const chosen = urlSession || list[0]?.id || "";
        setSelectedSessionId(chosen);
        if (chosen) {
          void fetchSummaryAndNotes(chosen);
        } else {
          setLoading(false);
        }
      })
      .catch(() => {
        if (!active) return;
        if (urlSession) {
          setSelectedSessionId(urlSession);
          void fetchSummaryAndNotes(urlSession);
        } else {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [fetchSummaryAndNotes]);

  const handleSelectSession = (sid: string) => {
    setSelectedSessionId(sid);
    setOkMsg("");
    setIsEditing(false);
    if (sid) void fetchSummaryAndNotes(sid);
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSessionId || generating) return;
    setGenerating(true);
    setErrorMsg("");
    setOkMsg("");
    try {
      const res = await aiFetch(
        `/api/v1/summaries/generate?session=${encodeURIComponent(selectedSessionId)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            lesson_title: genTitle.trim() || null,
            lecturer_notes: genLecturerNotes.trim() || null,
          }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: LessonSummaryRecord = await res.json();
      setSummary(data);
      setEditTitle(data.lesson_title);
      setEditOverview(data.overview);
      setEditTakeaways(data.key_takeaways.join("\n"));
      setShowGenForm(false);
      setOkMsg(`Đã tổng hợp bản tóm tắt AI (Phiên bản v${data.version_number}).`);
    } catch {
      setErrorMsg("Không thể tạo bản tóm tắt. Kiểm tra dịch vụ AI cổng 8000.");
    } finally {
      setGenerating(false);
    }
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSessionId) return;
    setGenerating(true);
    setErrorMsg("");
    try {
      const res = await aiFetch(
        `/api/v1/summaries?session=${encodeURIComponent(selectedSessionId)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            lesson_title: editTitle,
            overview: editOverview,
            key_takeaways: editTakeaways
              .split("\n")
              .map((s) => s.trim())
              .filter(Boolean),
          }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated: LessonSummaryRecord = await res.json();
      setSummary(updated);
      setIsEditing(false);
      setOkMsg(`Đã lưu chỉnh sửa tóm tắt (v${updated.version_number}).`);
    } catch {
      setErrorMsg("Không thể lưu chỉnh sửa bản tóm tắt.");
    } finally {
      setGenerating(false);
    }
  };

  const handleCopyAiToNote = async () => {
    if (!summary || !selectedSessionId) return;
    const compiled = [
      summary.overview,
      "",
      "Điểm chính cần nhớ:",
      ...summary.key_takeaways.map((t) => `- ${t}`),
    ].join("\n");
    setSavingNote(true);
    try {
      const res = await aiFetch(
        `/api/v1/summaries/notes?session=${encodeURIComponent(selectedSessionId)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: `Bản lưu AI: ${summary.lesson_title}`,
            content: compiled,
            source_type: "AI_COPY",
            is_pinned: true,
          }),
        },
      );
      if (res.ok) {
        const created: StudentNoteItem = await res.json();
        setNotes((prev) => [created, ...prev]);
        setOkMsg("Đã sao chép bản tóm tắt AI vào sổ tay ghi chú cá nhân.");
      }
    } finally {
      setSavingNote(false);
    }
  };

  const handleSaveNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSessionId || !noteTitle.trim() || savingNote) return;
    setSavingNote(true);
    try {
      const res = await aiFetch(
        `/api/v1/summaries/notes?session=${encodeURIComponent(selectedSessionId)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: noteTitle.trim(),
            content: noteContent,
            source_type: "PERSONAL",
            is_pinned: false,
          }),
        },
      );
      if (res.ok) {
        const created: StudentNoteItem = await res.json();
        setNotes((prev) => [created, ...prev]);
        setNoteTitle("");
        setNoteContent("");
        setOkMsg("Đã lưu ghi chú học tập.");
      }
    } finally {
      setSavingNote(false);
    }
  };

  const handleDeleteNote = async (noteId: string) => {
    if (!selectedSessionId) return;
    const res = await aiFetch(
      `/api/v1/summaries/notes/${encodeURIComponent(noteId)}?session=${encodeURIComponent(selectedSessionId)}`,
      { method: "DELETE" },
    );
    if (res.ok) {
      setNotes((prev) => prev.filter((n) => n.note_id !== noteId));
    }
  };

  const handleSendFeedback = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSessionId || sendingFeedback) return;
    setSendingFeedback(true);
    setErrorMsg("");
    try {
      const res = await studentService.submitSessionFeedback(
        selectedSessionId,
        rating,
        feedbackComment,
      );
      setFeedbackComment("");
      setOkMsg(res.message || "Đã gửi đánh giá buổi học thành công!");
    } catch {
      setErrorMsg("Không thể gửi đánh giá buổi học.");
    } finally {
      setSendingFeedback(false);
    }
  };

  return (
    <div className={styles.wrapper}>
      <div className={mode === "student" ? styles.studentShell : undefined}>
        {mode === "student" && (
          <div className={styles.topNav}>
            <button
              type="button"
              className={styles.backBtn}
              onClick={() => router.push("/sinhvien")}
            >
              <ArrowLeft size={16} /> Về trang chủ Sinh viên
            </button>
          </div>
        )}

        <header className={styles.headerCard}>
          <div className={styles.titleGroup}>
            <h1>
              {mode === "lecturer"
                ? "Tóm tắt bài giảng & Bản đồ nhiệt (Heatmap)"
                : "Tóm tắt bài giảng & Sổ tay học tập"}
            </h1>
            <p>
              Tổng hợp tự động lời giảng song ngữ, từ vựng chuyên ngành và các điểm sinh viên hỏi nhiều nhất trong buổi học.
            </p>
            {summary && (
              <div className={styles.metaBadges}>
                <span className={styles.badge}>
                  <Sparkles size={13} /> Chủ đề: {summary.detected_subject}
                </span>
                <span className={styles.badge}>
                  Phụ đề: {summary.transcript_count} câu
                </span>
                <span className={styles.badge}>
                  Câu hỏi SV: {summary.question_count}
                </span>
                <span className={styles.badge}>
                  Phiên bản v{summary.version_number} · {summary.model_name}
                </span>
              </div>
            )}
          </div>

          <div className={styles.controlsBar}>
            <select
              className={styles.sessionSelect}
              value={selectedSessionId}
              onChange={(e) => handleSelectSession(e.target.value)}
              aria-label="Chọn phiên học"
            >
              {sessions.length === 0 && (
                <option value={selectedSessionId}>
                  {selectedSessionId
                    ? `Phiên ${selectedSessionId.slice(0, 8)}…`
                    : "Chưa có phiên học nào"}
                </option>
              )}
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  [{s.status}] {s.classCode} — {s.title}
                </option>
              ))}
            </select>

            {selectedSessionId && (
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={() => void fetchSummaryAndNotes(selectedSessionId)}
                disabled={loading}
              >
                <RefreshCw size={15} /> Làm mới
              </button>
            )}

            {mode === "lecturer" && selectedSessionId && (
              <>
                <button
                  type="button"
                  className={styles.primaryBtn}
                  onClick={() => setShowGenForm((v) => !v)}
                  disabled={generating}
                >
                  <Sparkles size={15} /> Tạo / Cập nhật Tóm tắt AI
                </button>
                {summary && (
                  <button
                    type="button"
                    className={styles.secondaryBtn}
                    onClick={() => setIsEditing((v) => !v)}
                  >
                    <Edit3 size={15} /> {isEditing ? "Đóng sửa" : "Hiệu đính"}
                  </button>
                )}
              </>
            )}

            {summary && (
              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={() => window.print()}
              >
                <Printer size={15} /> Xuất PDF
              </button>
            )}
          </div>
        </header>

        {errorMsg && (
          <div className={`${styles.banner} ${styles.bannerError}`} role="alert">
            {errorMsg}
          </div>
        )}
        {okMsg && (
          <div className={`${styles.banner} ${styles.bannerOk}`} role="status">
            {okMsg}
          </div>
        )}

        {mode === "lecturer" && showGenForm && (
          <form onSubmit={handleGenerate} className={`${styles.card} ${styles.noPrint}`} style={{ marginBottom: 18 }}>
            <h3 className={styles.cardTitle} style={{ marginBottom: 12 }}>
              <Sparkles size={17} /> Tùy chọn tổng hợp Tóm tắt AI từ phiên học
            </h3>
            <div className={styles.formField}>
              <label htmlFor="gen-title">Tiêu đề bài giảng (để trống AI tự đặt theo chuyên đề)</label>
              <input
                id="gen-title"
                className={styles.input}
                value={genTitle}
                onChange={(e) => setGenTitle(e.target.value)}
                placeholder="VD: Bài 4 — Phát hiện & phòng tránh Deadlock trong Hệ phân tán"
              />
            </div>
            <div className={styles.formField}>
              <label htmlFor="gen-notes">Ghi chú dặn dò thêm của giảng viên (tuỳ chọn)</label>
              <textarea
                id="gen-notes"
                className={styles.textarea}
                rows={3}
                value={genLecturerNotes}
                onChange={(e) => setGenLecturerNotes(e.target.value)}
                placeholder="VD: Các em chú ý ôn kỹ 4 điều kiện Coffman cho bài kiểm tra giữa kỳ..."
              />
            </div>
            <button type="submit" className={styles.primaryBtn} disabled={generating}>
              <Sparkles size={15} /> {generating ? "Đang tổng hợp..." : "Chạy tổng hợp ngay"}
            </button>
          </form>
        )}

        {mode === "lecturer" && isEditing && summary && (
          <form onSubmit={handleSaveEdit} className={`${styles.card} ${styles.noPrint}`} style={{ marginBottom: 18 }}>
            <h3 className={styles.cardTitle} style={{ marginBottom: 12 }}>
              <Edit3 size={17} /> Hiệu đính nội dung bản tóm tắt
            </h3>
            <div className={styles.formField}>
              <label htmlFor="edit-title">Tiêu đề bài giảng</label>
              <input
                id="edit-title"
                className={styles.input}
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                required
              />
            </div>
            <div className={styles.formField}>
              <label htmlFor="edit-overview">Tổng quan bài giảng (Tiếng Việt)</label>
              <textarea
                id="edit-overview"
                className={styles.textarea}
                rows={4}
                value={editOverview}
                onChange={(e) => setEditOverview(e.target.value)}
              />
            </div>
            <div className={styles.formField}>
              <label htmlFor="edit-takeaways">Điểm chính cần nhớ (mỗi dòng 1 ý)</label>
              <textarea
                id="edit-takeaways"
                className={styles.textarea}
                rows={4}
                value={editTakeaways}
                onChange={(e) => setEditTakeaways(e.target.value)}
              />
            </div>
            <button type="submit" className={styles.primaryBtn} disabled={generating}>
              <Save size={15} /> Lưu phiên bản mới
            </button>
          </form>
        )}

        {!selectedSessionId && !loading ? (
          <div className={styles.card}>
            <p className={styles.prose}>
              Bạn chưa có phiên học nào đã diễn ra. Hãy tham gia hoặc khởi tạo một buổi học để xem tóm tắt bài giảng.
            </p>
          </div>
        ) : loading ? (
          <div className={styles.card}>
            <p className={styles.prose}>Đang tải bản tóm tắt bài giảng và dữ liệu tương tác...</p>
          </div>
        ) : summary ? (
          <div className={styles.gridTwo}>
            {/* CỘT TRÁI: NỘI DUNG TÓM TẮT HỌC THUẬT */}
            <div className={styles.stack}>
              <section className={styles.card}>
                <div className={styles.cardHeader}>
                  <h2 className={styles.cardTitle}>
                    <FileText size={18} color="#2563eb" /> {summary.lesson_title}
                  </h2>
                  <button
                    type="button"
                    className={`${styles.secondaryBtn} ${styles.noPrint}`}
                    onClick={() => void handleCopyAiToNote()}
                    disabled={savingNote}
                  >
                    <Copy size={14} /> Lưu vào ghi chú
                  </button>
                </div>
                <p className={styles.prose}>{summary.overview}</p>
                {summary.overview_en && (
                  <div className={styles.enBox}>
                    <strong>English Summary:</strong> {summary.overview_en}
                  </div>
                )}
              </section>

              {summary.key_takeaways.length > 0 && (
                <section className={styles.card}>
                  <div className={styles.cardHeader}>
                    <h3 className={styles.cardTitle}>
                      <CheckCircle2 size={18} color="#16a34a" /> Điểm chính cần nhớ (Key Takeaways)
                    </h3>
                  </div>
                  <ul className={styles.takeawayList}>
                    {summary.key_takeaways.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </section>
              )}

              {summary.lecture_structure.length > 0 && (
                <section className={styles.card}>
                  <div className={styles.cardHeader}>
                    <h3 className={styles.cardTitle}>
                      <Layers size={18} color="#7c3aed" /> Cấu trúc dòng chảy bài giảng
                    </h3>
                  </div>
                  {summary.lecture_structure.map((sec) => (
                    <div key={sec.section_index} className={styles.sectionItem}>
                      <div className={styles.sectionMeta}>
                        <strong>
                          Phần {sec.section_index}: {sec.title}
                        </strong>
                        {sec.time_range && (
                          <span className={styles.timeTag}>{sec.time_range}</span>
                        )}
                      </div>
                      <p className={styles.prose}>{sec.summary_vi}</p>
                    </div>
                  ))}
                </section>
              )}

              {summary.vocabulary.length > 0 && (
                <section className={styles.card}>
                  <div className={styles.cardHeader}>
                    <h3 className={styles.cardTitle}>
                      <BookMarked size={18} color="#0284c7" /> Từ vựng chuyên ngành Song ngữ (Domain Keywords)
                    </h3>
                  </div>
                  <div className={styles.vocabGrid}>
                    {summary.vocabulary.map((v, idx) => (
                      <div key={idx} className={styles.vocabCard}>
                        <div className={styles.vocabTerm}>{v.term_en}</div>
                        <div className={styles.vocabVi}>{v.term_vi}</div>
                        {v.explanation_vi && (
                          <div className={styles.vocabDesc}>{v.explanation_vi}</div>
                        )}
                        {v.definition_en && (
                          <div className={styles.vocabDesc} style={{ fontStyle: "italic" }}>
                            EN: {v.definition_en}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {summary.examples.length > 0 && (
                <section className={styles.card}>
                  <div className={styles.cardHeader}>
                    <h3 className={styles.cardTitle}>
                      <Lightbulb size={18} color="#d97706" /> Ví dụ minh họa trong giờ giảng
                    </h3>
                  </div>
                  {summary.examples.map((ex, idx) => (
                    <div key={idx} className={styles.sectionItem}>
                      {ex.timestamp && <span className={styles.timeTag}>{ex.timestamp}</span>}
                      <p className={styles.prose}>{ex.text_vi}</p>
                      {ex.text_en && <div className={styles.enBox}>{ex.text_en}</div>}
                    </div>
                  ))}
                </section>
              )}
            </div>

            {/* CỘT PHẢI: HEATMAP, ĐIỂM KHÓ HIỂU, GHI CHÚ & ĐÁNH GIÁ */}
            <div className={styles.stack}>
              <section className={styles.card}>
                <div className={styles.cardHeader}>
                  <h3 className={styles.cardTitle}>
                    <Flame size={18} color="#ef4444" /> Bản đồ nhiệt mức độ thắc mắc theo Slide
                  </h3>
                </div>
                {summary.heatmap.length === 0 ? (
                  <p className={styles.prose}>
                    Chưa ghi nhận dữ liệu chuyển slide PDF trong phiên học này. Khi giảng viên trình chiếu slide trong phòng học, mật độ câu hỏi theo từng trang sẽ hiển thị tại đây.
                  </p>
                ) : (
                  <div className={styles.heatmapGrid}>
                    {summary.heatmap.map((h) => (
                      <div key={h.slide_number} className={styles.heatRow}>
                        <strong>Slide {h.slide_number}</strong>
                        <div className={styles.heatTrack}>
                          <div
                            className={`${styles.heatFill} ${styles[`heat_${h.heat_level}`]}`}
                            style={{ width: `${Math.max(8, h.intensity_pct)}%` }}
                          />
                        </div>
                        <span>{h.question_count} câu hỏi</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className={styles.card}>
                <div className={styles.cardHeader}>
                  <h3 className={styles.cardTitle}>
                    <AlertTriangle size={18} color="#d97706" /> Điểm sinh viên thắc mắc nhiều & Giải đáp
                  </h3>
                </div>
                {summary.further_clarification.length === 0 ? (
                  <p className={styles.prose}>Chưa có câu hỏi ẩn danh nào được gửi trong phiên này.</p>
                ) : (
                  summary.further_clarification.map((item, idx) => (
                    <div key={idx} className={styles.clarItem}>
                      <div className={styles.clarTop}>
                        <strong>{item.question_count} lượt hỏi tương đồng</strong>
                        <span
                          className={
                            item.status === "answered"
                              ? styles.statusAnswered
                              : styles.statusPending
                          }
                        >
                          {item.status === "answered" ? "Đã giải đáp" : "Cần làm rõ thêm"}
                        </span>
                      </div>
                      <p className={styles.prose} style={{ fontWeight: 600 }}>
                        “{item.topic}”
                      </p>
                      {item.answer_text ? (
                        <div className={styles.enBox} style={{ borderLeftColor: "#10b981" }}>
                          <strong>Trả lời của Giảng viên:</strong> {item.answer_text}
                        </div>
                      ) : (
                        <p className={styles.vocabDesc}>{item.recommendation}</p>
                      )}
                    </div>
                  ))
                )}
              </section>

              {/* SỔ TAY GHI CHÚ CÁ NHÂN */}
              <section className={`${styles.card} ${styles.noPrint}`}>
                <div className={styles.cardHeader}>
                  <h3 className={styles.cardTitle}>
                    <BookMarked size={18} color="#2563eb" /> Ghi chú cá nhân của tôi
                  </h3>
                </div>
                <form onSubmit={handleSaveNote}>
                  <div className={styles.formField}>
                    <input
                      className={styles.input}
                      placeholder="Tiêu đề ghi chú..."
                      value={noteTitle}
                      onChange={(e) => setNoteTitle(e.target.value)}
                      required
                    />
                  </div>
                  <div className={styles.formField}>
                    <textarea
                      className={styles.textarea}
                      rows={3}
                      placeholder="Ghi lại ý hiểu của bạn hoặc câu cần ôn tập..."
                      value={noteContent}
                      onChange={(e) => setNoteContent(e.target.value)}
                    />
                  </div>
                  <button type="submit" className={styles.primaryBtn} disabled={savingNote}>
                    <Save size={14} /> Lưu ghi chú
                  </button>
                </form>

                {notes.map((n) => (
                  <div key={n.note_id} className={styles.noteCard}>
                    <div className={styles.clarTop}>
                      <strong>{n.title}</strong>
                      <button
                        type="button"
                        onClick={() => void handleDeleteNote(n.note_id)}
                        style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer" }}
                        aria-label="Xóa ghi chú"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                    <p className={styles.prose}>{n.content}</p>
                  </div>
                ))}
              </section>

              {/* PHẢN HỒI & ĐÁNH GIÁ BUỔI HỌC */}
              <section className={`${styles.card} ${styles.noPrint}`}>
                <div className={styles.cardHeader}>
                  <h3 className={styles.cardTitle}>Đánh giá buổi học & chất lượng phụ đề</h3>
                </div>
                <form onSubmit={handleSendFeedback}>
                  <div className={styles.starRow}>
                    {[1, 2, 3, 4, 5].map((star) => (
                      <button
                        key={star}
                        type="button"
                        className={`${styles.starBtn} ${rating >= star ? styles.starActive : ""}`}
                        onClick={() => setRating(star)}
                      >
                        ★ {star}
                      </button>
                    ))}
                  </div>
                  <div className={styles.formField}>
                    <textarea
                      className={styles.textarea}
                      rows={2}
                      placeholder="Nhận xét về nội dung bài giảng hoặc độ chính xác bản dịch..."
                      value={feedbackComment}
                      onChange={(e) => setFeedbackComment(e.target.value)}
                    />
                  </div>
                  <button type="submit" className={styles.secondaryBtn} disabled={sendingFeedback}>
                    {sendingFeedback ? "Đang gửi..." : "Gửi đánh giá"}
                  </button>
                </form>
              </section>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
