"use client";

import React, { useState, useEffect, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import studentService from "../../services/student.service";
import { aiUrl, aiWsUrl } from "../../lib/ai";
import QAToast from "../../components/room/QAToast/QAToast";

interface QuestionItem {
  id: string;
  text: string;
  timestamp: string;
}

interface SessionInfo {
  id: string;
  title: string;
  status: string;
  startedAt: string | null;
  class: { id: string; code: string; name: string };
  lecturerName: string;
}

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  LIVE: { text: "Trực tiếp", color: "#10b981" },
  SCHEDULED: { text: "Chưa bắt đầu", color: "#f59e0b" },
  ENDED: { text: "Đã kết thúc", color: "#64748b" },
  CANCELLED: { text: "Đã hủy", color: "#ef4444" },
};

interface AnswerOutput {
  representative_id: string;
  representative_text: string;
  total_count: number;
  answer_text: string;
  answered_at: string;
}

export default function StudentClassroom() {
  // sessionId có khi vào từ /sinhvien/classroom/[sessionId]; không có khi mở /student (chế độ cũ)
  const { sessionId } = useParams<{ sessionId?: string }>();
  const router = useRouter();
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(Boolean(sessionId));
  const [loadError, setLoadError] = useState("");
  const joinedRef = useRef(false);

  // Tải thông tin phiên + điểm danh vào lớp (chỉ khi LIVE); rời lớp khi thoát trang
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const session: SessionInfo = await studentService.getSession(sessionId);
        if (cancelled) return;
        setInfo(session);
        if (session.status === "LIVE") {
          await studentService.joinSession(sessionId);
          joinedRef.current = true;
        }
      } catch (err: any) {
        if (!cancelled) {
          setLoadError(
            err.response?.data?.message ||
              (err.response ? "Không thể tải phiên học." : "Không kết nối được máy chủ."),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (joinedRef.current) {
        joinedRef.current = false;
        void studentService.leaveSession(sessionId).catch(() => {});
      }
    };
  }, [sessionId]);

  // Phòng chờ: hỏi lại trạng thái mỗi 8 giây cho tới khi giảng viên bắt đầu buổi học
  useEffect(() => {
    if (!sessionId || info?.status !== "SCHEDULED") return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const fresh: SessionInfo = await studentService.getSession(sessionId);
        if (stopped) return;
        setInfo(fresh);
        if (fresh.status === "LIVE") {
          await studentService.joinSession(sessionId);
          joinedRef.current = true;
        }
      } catch {
        /* thử lại ở lượt sau */
      }
    }, 8000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [sessionId, info?.status]);

  const [questionText, setQuestionText] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [successNotif, setSuccessNotif] = useState(false);
  const [transcripts, setTranscripts] = useState<Array<{ id: number; en: string; vi: string; time: string }>>([]);
  const [answers, setAnswers] = useState<AnswerOutput[]>([]);
  const [viewMode, setViewMode] = useState<"transcript" | "qa">("transcript");

  const bottomRef = useRef<HTMLDivElement>(null);

  // [CUSTOM] WebSocket real-time — kết nối tới /api/v1/ws/qa (xem
  // be/service/qa_broadcast.py). Sinh viên chỉ lắng nghe, không gửi gì.
  // Ngay khi kết nối nhận 1 "snapshot" toàn bộ câu trả lời hiện có (không
  // bỏ lỡ câu đã trả lời trước khi vào phòng), sau đó nhận "upsert"/
  // "remove" ngay khi giảng viên gửi hoặc xoá câu trả lời trên Dashboard.
  // Đã xếp hạng sẵn ở backend theo total_count giảm dần.
  useEffect(() => {
    const wsUrl = aiWsUrl("/api/v1/ws/qa");
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "snapshot") {
          setAnswers(msg.answers ?? []);
        } else if (msg.type === "upsert") {
          setAnswers((prev) => {
            const next = prev.filter((a) => a.representative_id !== msg.answer.representative_id);
            next.push(msg.answer);
            next.sort((a, b) => b.total_count - a.total_count || a.answered_at.localeCompare(b.answered_at));
            return next;
          });
        } else if (msg.type === "remove") {
          setAnswers((prev) => prev.filter((a) => a.representative_id !== msg.representative_id));
        }
      } catch (err) {
        console.warn("Q&A WebSocket parse error:", err);
      }
    };

    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    const wsUrl = aiWsUrl("/api/v1/ws/live-translate", { role: "viewer", progressive: 1 });
    const ws = new WebSocket(wsUrl);

    const upsertLine = (id: number, patch: Partial<{ en: string; vi: string; time: string }>) =>
      setTranscripts((prev) => {
        const i = prev.findIndex((t) => t.id === id);
        if (i === -1) return [...prev, { id, en: "", vi: "", time: "", ...patch }];
        const next = [...prev];
        next[i] = { ...next[i], ...patch };
        return next;
      });

    const handle = (data: any) => {
      if (data.type === "history") {
        (data.items ?? []).forEach(handle);
        return;
      }
      if (data.type === "final") {
        upsertLine(data.segment_id, {
          [data.source_lang === "en" ? "en" : "vi"]: data.original_text,
          time: data.timestamp,
        });
      } else if (data.type === "translation") {
        upsertLine(data.segment_id, { [data.target_lang === "en" ? "en" : "vi"]: data.translated_text });
      } else if (data.type === "result") {
        upsertLine(data.segment_id, {
          [data.source_lang === "en" ? "en" : "vi"]: data.original_text,
          [data.target_lang === "en" ? "en" : "vi"]: data.translated_text,
          time: data.timestamp,
        });
      }
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    ws.onmessage = (event) => {
      try {
        handle(JSON.parse(event.data));
      } catch (err) {
        console.warn("WebSocket parse error:", err);
      }
    };

    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const handleSendQuestion = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanText = questionText.trim();
    if (!cleanText || isSending) return;

    setIsSending(true);
    const newQuestion: QuestionItem = {
      id: `std_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
      text: cleanText,
      timestamp: new Date().toISOString(),
    };

    // [GIỮ NGUYÊN — không xoá theo yêu cầu] cache cục bộ cũ. Không còn ai
    // đọc lại giá trị này (Dashboard giờ lấy dữ liệu chung từ server, xem
    // be/service/question_store.py) nhưng giữ lại làm bản sao cục bộ.
    const rawSaved = localStorage.getItem("room_questions");
    const currentQuestions: QuestionItem[] = rawSaved ? JSON.parse(rawSaved) : [];
    const updated = [...currentQuestions, newQuestion];
    localStorage.setItem("room_questions", JSON.stringify(updated));

    // Thêm AbortController giới hạn tối đa 5s nếu backend treo
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      // [SỬA] Gửi 1 câu hỏi lên kho chung phía server (POST /api/v1/questions)
      // thay vì tự gom cả danh sách từ localStorage rồi POST /aggregate —
      // để câu hỏi từ MỌI thiết bị đều tới được Dashboard giảng viên, không
      // chỉ thiết bị của chính người gửi.
      const backendUrl = aiUrl("/api/v1/questions");

      const res = await fetch(backendUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newQuestion),
        signal: controller.signal,
      });

      if (!res.ok) throw new Error(`HTTP Error: ${res.status}`);

      setQuestionText("");
      setSuccessNotif(true);
      setTimeout(() => setSuccessNotif(false), 2500);
    } catch (error: any) {
      console.error("Lỗi gửi câu hỏi:", error);
      alert("Không kết nối được Backend AI (Port 8000). Vui lòng kiểm tra lại server!");
    } finally {
      clearTimeout(timeoutId);
      setIsSending(false);
    }
  };

  if (sessionId && loading) {
    return (
      <div style={{ minHeight: "100dvh", display: "grid", placeItems: "center", background: "#0b1120", color: "#94a3b8" }}>
        Đang vào lớp học...
      </div>
    );
  }

  if (sessionId && loadError) {
    return (
      <div style={{ minHeight: "100dvh", display: "flex", flexDirection: "column", gap: 16, alignItems: "center", justifyContent: "center", background: "#0b1120", color: "#fca5a5", padding: 24, textAlign: "center" }}>
        <p>{loadError}</p>
        <button
          onClick={() => router.push("/sinhvien")}
          style={{ background: "#2563eb", color: "#fff", border: "none", borderRadius: 6, padding: "10px 18px", fontWeight: 600, cursor: "pointer" }}
        >
          Về trang chủ sinh viên
        </button>
      </div>
    );
  }

  const status = info ? (STATUS_LABEL[info.status] ?? { text: info.status, color: "#64748b" }) : null;
  const isLive = !info || info.status === "LIVE";

  return (
    <div style={{ 
      width: "100%", 
      maxWidth: "600px", 
      margin: "0 auto", 
      height: "100dvh", // Sử dụng 100dvh thay vì 100vh để khớp chính xác với khung nhìn thực tế trên mobile
      display: "flex", 
      flexDirection: "column", 
      background: "#0b1120", 
      color: "#f8fafc", 
      fontFamily: "sans-serif",
      boxSizing: "border-box",
      overflow: "hidden"
    }}>
      <QAToast />
      {/* Mobile Header */}
      <header style={{ padding: "12px 16px", background: "#1e293b", borderBottom: "1px solid #334155", display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          {sessionId && (
            <button
              onClick={() => router.push("/sinhvien")}
              aria-label="Rời lớp"
              style={{ background: "transparent", border: "1px solid #475569", color: "#cbd5e1", borderRadius: 6, padding: "4px 8px", cursor: "pointer", flexShrink: 0 }}
            >
              ←
            </button>
          )}
          <div style={{ minWidth: 0 }}>
            <h2 style={{ fontSize: "16px", margin: 0, color: "#38bdf8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {info ? info.class.name : "ClassBridge Live"}
            </h2>
            <small style={{ color: "#94a3b8" }}>
              {info ? `${info.title} · GV ${info.lecturerName}` : "Phòng học EMI trực tuyến"}
            </small>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          {sessionId && (
            <button
              onClick={() => router.push(`/sinhvien/classroom/${encodeURIComponent(sessionId)}/chat`)}
              style={{ background: "transparent", border: "1px solid #475569", color: "#cbd5e1", borderRadius: 6, padding: "3px 8px", fontSize: 11, cursor: "pointer" }}
            >
              Chat lớp
            </button>
          )}
          <span style={{ fontSize: "11px", background: status?.color ?? "#10b981", color: "#fff", padding: "2px 8px", borderRadius: "12px", fontWeight: "bold" }}>
            {status?.text ?? "Trực tiếp"}
          </span>
        </div>
      </header>

      {!isLive && info && (
        <div style={{ background: "#422006", color: "#fcd34d", fontSize: 12, padding: "8px 16px", textAlign: "center", flexShrink: 0 }}>
          {info.status === "SCHEDULED"
            ? "Phòng chờ: giảng viên chưa bắt đầu buổi học. Trang sẽ tự cập nhật và phụ đề sẽ xuất hiện khi buổi học bắt đầu."
            : "Buổi học này không còn diễn ra."}
        </div>
      )}

      {/* Chuyển đổi Transcript / Q&A */}
      <div style={{ display: "flex", borderBottom: "1px solid #334155", flexShrink: 0 }}>
        <button
          onClick={() => setViewMode("transcript")}
          style={{
            flex: 1, padding: "10px", fontSize: "13px", fontWeight: 600, border: "none", cursor: "pointer",
            background: viewMode === "transcript" ? "#1e293b" : "transparent",
            color: viewMode === "transcript" ? "#38bdf8" : "#94a3b8",
            borderBottom: viewMode === "transcript" ? "2px solid #38bdf8" : "2px solid transparent",
          }}
        >
          Phụ đề
        </button>
        <button
          onClick={() => setViewMode("qa")}
          style={{
            flex: 1, padding: "10px", fontSize: "13px", fontWeight: 600, border: "none", cursor: "pointer",
            background: viewMode === "qa" ? "#1e293b" : "transparent",
            color: viewMode === "qa" ? "#38bdf8" : "#94a3b8",
            borderBottom: viewMode === "qa" ? "2px solid #38bdf8" : "2px solid transparent",
          }}
        >
          Q&A {answers.length > 0 ? `(${answers.length})` : ""}
        </button>
      </div>

      {/* Luồng phụ đề trực tiếp (Thêm minHeight: 0 để flex container cuộn mượt mà không bị đẩy vỡ) */}
      {viewMode === "transcript" ? (
        <main style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: "12px" }}>
          {transcripts.length === 0 ? (
            <div style={{ textAlign: "center", color: "#64748b", marginTop: "40px" }}>
              <p>Đang chờ giảng viên phát âm thanh...</p>
              <small>Phụ đề song ngữ sẽ hiển thị trực tiếp tại đây.</small>
            </div>
          ) : (
            transcripts.map((t) => (
              <div key={t.id} style={{ background: "#1e293b", padding: "10px 14px", borderRadius: "8px", borderLeft: "3px solid #38bdf8", wordBreak: "break-word" }}>
                <div style={{ fontSize: "14px", color: "#f1f5f9", marginBottom: "4px" }}>{t.en}</div>
                <div style={{ fontSize: "13px", color: "#94a3b8" }}>{t.vi}</div>
                <div style={{ fontSize: "10px", color: "#64748b", textAlign: "right", marginTop: "4px" }}>{t.time}</div>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </main>
      ) : (
        <main style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: "12px" }}>
          {answers.length === 0 ? (
            <div style={{ textAlign: "center", color: "#64748b", marginTop: "40px" }}>
              <p>Chưa có câu hỏi nào được trả lời.</p>
              <small>Câu trả lời của giảng viên sẽ hiện tại đây, chủ đề nhiều bạn hỏi nhất lên đầu.</small>
            </div>
          ) : (
            answers.map((a) => (
              <div key={a.representative_id} style={{ background: "#1e293b", padding: "12px 14px", borderRadius: "8px", borderLeft: "3px solid #10b981", wordBreak: "break-word" }}>
                <div style={{ fontSize: "11px", color: "#38bdf8", fontWeight: 600, marginBottom: "4px" }}>
                  {a.total_count} bạn hỏi tương tự
                </div>
                <div style={{ fontSize: "14px", color: "#f1f5f9", marginBottom: "6px" }}>{a.representative_text}</div>
                <div style={{ fontSize: "13px", color: "#a7f3d0", background: "#0b1120", padding: "8px 10px", borderRadius: "6px" }}>
                  {a.answer_text}
                </div>
              </div>
            ))
          )}
        </main>
      )}

      {/* Form đặt câu hỏi ẩn danh */}
      <footer style={{ padding: "12px 16px", background: "#1e293b", borderTop: "1px solid #334155", flexShrink: 0 }}>
        {successNotif && (
          <div style={{ background: "#065f46", color: "#a7f3d0", padding: "6px 12px", borderRadius: "6px", fontSize: "12px", marginBottom: "8px", textAlign: "center" }}>
            ✓ Đã gửi câu hỏi ẩn danh thành công!
          </div>
        )}
        <form onSubmit={handleSendQuestion} style={{ display: "flex", gap: "8px" }}>
          <input
            type="text"
            placeholder="Hỏi ẩn danh (EN hoặc VI)..."
            value={questionText}
            onChange={(e) => setQuestionText(e.target.value)}
            style={{ flex: 1, minWidth: 0, padding: "10px 14px", borderRadius: "6px", border: "1px solid #475569", background: "#0f172a", color: "#fff", fontSize: "14px", outline: "none" }}
          />
          <button
            type="submit"
            disabled={isSending || !questionText.trim()}
            style={{ 
              background: isSending || !questionText.trim() ? "#475569" : "#2563eb", 
              color: isSending || !questionText.trim() ? "#94a3b8" : "#ffffff", 
              border: "none", 
              padding: "10px 16px", 
              borderRadius: "6px", 
              fontWeight: 600, 
              fontSize: "13px", 
              cursor: isSending || !questionText.trim() ? "not-allowed" : "pointer", 
              whiteSpace: "nowrap",
              transition: "background-color 0.2s"
            }}
          >
            {isSending ? "Đang gửi..." : "Gửi"}
          </button>
        </form>
      </footer>
    </div>
  );
}