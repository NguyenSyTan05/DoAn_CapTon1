"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import studentService from "../../services/student.service";
import { aiFetch, aiWsUrl, isAiAccessStatus } from "../../lib/ai";
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
  answer_vi?: string;
  answer_en?: string;
}

interface RagCitation {
  label: string;
  source_type: "SLIDE" | "TRANSCRIPT";
  slide_number?: number | null;
  excerpt: string;
  score: number;
}

interface RagTurn {
  message_id: string;
  question: string;
  answer: string;
  status: "ANSWERED" | "NO_SOURCE_FOUND";
  citations: RagCitation[];
  can_escalate?: boolean;
  escalated?: boolean;
}

interface QuickQuestionOption {
  id: string;
  text: string;
  imageDataUrl: string | null;
  isCorrect: boolean | null;
}

interface QuickQuestionItem {
  id: string;
  question: string;
  questionType: "POLL" | "MULTIPLE_CHOICE" | "TRUE_FALSE" | "SHORT_ANSWER" | "ORDERING" | "MATCHING";
  payload: { leftItems?: string[]; rightItems?: string[]; correctOrder?: string[] };
  options: QuickQuestionOption[];
  myResponse: {
    selectedOptionId: string | null;
    answerText: string | null;
    isCorrect: boolean | null;
    submittedAt: string | null;
  } | null;
}

export default function StudentClassroom() {
  const { sessionId } = useParams<{ sessionId?: string }>();
  const router = useRouter();
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [loading, setLoading] = useState(Boolean(sessionId));
  const [loadError, setLoadError] = useState("");
  const joinedRef = useRef(false);

  const [questionText, setQuestionText] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [successNotif, setSuccessNotif] = useState(false);
  const [transcripts, setTranscripts] = useState<Array<{ id: number; en: string; vi: string; time: string }>>([]);
  const [answers, setAnswers] = useState<AnswerOutput[]>([]);
  const [quickQuestions, setQuickQuestions] = useState<QuickQuestionItem[]>([]);
  const [quizDrafts, setQuizDrafts] = useState<Record<string, any>>({});
  const [submittingQuizId, setSubmittingQuizId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"transcript" | "qa" | "quiz" | "chatbot">("transcript");
  const [ragTurns, setRagTurns] = useState<RagTurn[]>([]);
  const [ragInput, setRagInput] = useState("");
  const [askingRag, setAskingRag] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);

  const loadQuickQuestions = useCallback(async () => {
    if (!sessionId) return;
    try {
      const list = await studentService.getQuickQuestions(sessionId);
      setQuickQuestions(list);
    } catch {
      /* bỏ qua nếu chưa có câu hỏi nhanh */
    }
  }, [sessionId]);

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
          await loadQuickQuestions();
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
  }, [sessionId, loadQuickQuestions]);

  useEffect(() => {
    if (!sessionId || info?.status !== "LIVE") return;
    const timer = window.setInterval(() => void loadQuickQuestions(), 10000);
    return () => window.clearInterval(timer);
  }, [sessionId, info?.status, loadQuickQuestions]);

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
          await loadQuickQuestions();
        }
      } catch (err) {
        const data = (err as { response?: { data?: { code?: string; message?: string } } }).response?.data;
        if (!stopped && data?.code === "session_closed") {
          setLoadError(data.message || "Phiên học đã kết thúc hoặc bị huỷ.");
        }
      }
    }, 8000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [sessionId, info?.status, loadQuickQuestions]);

  // WebSocket Q&A có auto-reconnect
  useEffect(() => {
    let active = true;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (!active) return;
      ws = new WebSocket(aiWsUrl("/api/v1/ws/qa"));
      ws.onmessage = (event) => {
        if (!active) return;
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
      ws.onclose = (ev) => {
        if (!active || ev.code === 1008) return;
        reconnectTimer = setTimeout(connect, 2500);
      };
    };

    connect();
    return () => {
      active = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        ws.close();
      }
    };
  }, [sessionId]);

  // WebSocket Phụ đề trực tiếp có auto-reconnect
  useEffect(() => {
    let active = true;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const upsertLine = (id: number, patch: Partial<{ en: string; vi: string; time: string }>) =>
      setTranscripts((prev) => {
        const i = prev.findIndex((t) => t.id === id);
        if (i === -1) return [...prev, { id, en: "", vi: "", time: "", ...patch }];
        const next = [...prev];
        next[i] = { ...next[i], ...patch };
        return next;
      });

    const handle = (data: any) => {
      if (data.type === "clear") {
        setTranscripts([]);
        return;
      }
      if (data.type === "history") {
        setTranscripts([]);
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

    const connect = () => {
      if (!active) return;
      ws = new WebSocket(aiWsUrl("/api/v1/ws/live-translate", { role: "viewer", progressive: 1 }));
      ws.onmessage = (event) => {
        if (!active) return;
        try {
          handle(JSON.parse(event.data));
        } catch (err) {
          console.warn("WebSocket parse error:", err);
        }
      };
      ws.onclose = (ev) => {
        if (!active || ev.code === 1008) return;
        reconnectTimer = setTimeout(connect, 2000);
      };
    };

    connect();
    return () => {
      active = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        ws.close();
      }
    };
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

    try {
      const rawSaved = localStorage.getItem("room_questions");
      const currentQuestions: QuestionItem[] = rawSaved ? JSON.parse(rawSaved) : [];
      localStorage.setItem("room_questions", JSON.stringify([...currentQuestions.slice(-199), newQuestion]));
    } catch {
      localStorage.setItem("room_questions", JSON.stringify([newQuestion]));
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const res = await aiFetch("/api/v1/questions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newQuestion),
        signal: controller.signal,
      });

      if (isAiAccessStatus(res.status)) return;
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

  const handleSubmitQuiz = async (q: QuickQuestionItem) => {
    if (!sessionId || submittingQuizId) return;
    const draft = quizDrafts[q.id];
    let payload: Record<string, any> = {};

    if (q.questionType === "POLL" || q.questionType === "MULTIPLE_CHOICE" || q.questionType === "TRUE_FALSE") {
      if (!draft) return;
      payload = { selectedOptionId: draft };
    } else if (q.questionType === "SHORT_ANSWER") {
      if (!draft?.trim()) return;
      payload = { answerText: draft.trim() };
    } else if (q.questionType === "ORDERING") {
      const currentOrder: string[] = draft ?? q.options.map((o) => o.text);
      payload = { orderedItems: currentOrder };
    } else if (q.questionType === "MATCHING") {
      const mapObj: Record<string, string> = draft ?? {};
      const lefts = q.payload.leftItems ?? [];
      if (lefts.some((l) => !mapObj[l])) {
        alert("Vui lòng chọn vế nối cho tất cả các mục.");
        return;
      }
      payload = { pairs: lefts.map((l) => ({ left: l, right: mapObj[l] })) };
    }

    setSubmittingQuizId(q.id);
    try {
      await studentService.respondQuickQuestion(sessionId, q.id, payload);
      await loadQuickQuestions();
    } catch (err: any) {
      alert(err?.response?.data?.message || "Không thể gửi câu trả lời.");
    } finally {
      setSubmittingQuizId(null);
    }
  };

  const handleAskChatbot = async (e: React.FormEvent) => {
    e.preventDefault();
    const clean = ragInput.trim();
    if (!clean || askingRag) return;
    setAskingRag(true);
    try {
      const res = await aiFetch("/api/v1/chatbot/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: clean }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        alert(errBody?.detail?.message || "Không thể hỏi Trợ lý AI lúc này.");
        return;
      }
      const turn: RagTurn = await res.json();
      setRagTurns((prev) => [...prev, turn]);
      setRagInput("");
    } catch {
      alert("Không kết nối được dịch vụ AI Học liệu (Port 8000).");
    } finally {
      setAskingRag(false);
    }
  };

  const handleEscalateTurn = async (turn: RagTurn) => {
    try {
      const res = await aiFetch("/api/v1/chatbot/escalate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: turn.question }),
      });
      if (res.ok) {
        setRagTurns((prev) =>
          prev.map((t) => (t.message_id === turn.message_id ? { ...t, escalated: true } : t)),
        );
      }
    } catch {
      alert("Không thể chuyển tiếp câu hỏi lúc này.");
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
        <div style={{ display: "flex", gap: 10 }}>
          {sessionId && (
            <button
              onClick={() => router.push(`/summary?session=${encodeURIComponent(sessionId)}`)}
              style={{ background: "#0f766e", color: "#fff", border: "none", borderRadius: 6, padding: "10px 16px", fontWeight: 600, cursor: "pointer" }}
            >
              Xem Tóm tắt bài giảng
            </button>
          )}
          <button
            onClick={() => router.push("/sinhvien")}
            style={{ background: "#2563eb", color: "#fff", border: "none", borderRadius: 6, padding: "10px 18px", fontWeight: 600, cursor: "pointer" }}
          >
            Về trang chủ sinh viên
          </button>
        </div>
      </div>
    );
  }

  const status = info ? (STATUS_LABEL[info.status] ?? { text: info.status, color: "#64748b" }) : null;
  const isLive = !info || info.status === "LIVE";
  const unansweredQuizCount = quickQuestions.filter((q) => !q.myResponse).length;

  return (
    <div style={{
      width: "100%",
      maxWidth: "600px",
      margin: "0 auto",
      height: "100dvh",
      display: "flex",
      flexDirection: "column",
      background: "#0b1120",
      color: "#f8fafc",
      fontFamily: "sans-serif",
      boxSizing: "border-box",
      overflow: "hidden",
    }}>
      <QAToast />
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
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          {sessionId && (
            <>
              <button
                onClick={() => router.push(`/summary?session=${encodeURIComponent(sessionId)}`)}
                style={{ background: "transparent", border: "1px solid #475569", color: "#cbd5e1", borderRadius: 6, padding: "3px 8px", fontSize: 11, cursor: "pointer" }}
              >
                Tóm tắt
              </button>
              <button
                onClick={() => router.push(`/sinhvien/classroom/${encodeURIComponent(sessionId)}/chat`)}
                style={{ background: "transparent", border: "1px solid #475569", color: "#cbd5e1", borderRadius: 6, padding: "3px 8px", fontSize: 11, cursor: "pointer" }}
              >
                Chat
              </button>
            </>
          )}
          <span style={{ fontSize: "11px", background: status?.color ?? "#10b981", color: "#fff", padding: "2px 8px", borderRadius: "12px", fontWeight: "bold" }}>
            {status?.text ?? "Trực tiếp"}
          </span>
        </div>
      </header>

      {!isLive && info && (
        <div style={{ background: "#422006", color: "#fcd34d", fontSize: 12, padding: "8px 16px", textAlign: "center", flexShrink: 0 }}>
          {info.status === "SCHEDULED"
            ? "Phòng chờ: giảng viên chưa bắt đầu buổi học. Trang sẽ tự cập nhật khi buổi học bắt đầu."
            : "Buổi học này không còn diễn ra."}
        </div>
      )}

      {/* Chuyển đổi Phụ đề / Q&A / Câu hỏi nhanh */}
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
        {sessionId && (
          <>
            <button
              onClick={() => {
                setViewMode("quiz");
                void loadQuickQuestions();
              }}
              style={{
                flex: 1, padding: "10px", fontSize: "13px", fontWeight: 600, border: "none", cursor: "pointer",
                background: viewMode === "quiz" ? "#1e293b" : "transparent",
                color: viewMode === "quiz" ? "#38bdf8" : "#94a3b8",
                borderBottom: viewMode === "quiz" ? "2px solid #38bdf8" : "2px solid transparent",
              }}
            >
              Quiz {unansweredQuizCount > 0 ? `(${unansweredQuizCount} mới)` : quickQuestions.length > 0 ? `(${quickQuestions.length})` : ""}
            </button>
            <button
              onClick={() => setViewMode("chatbot")}
              style={{
                flex: 1, padding: "10px", fontSize: "13px", fontWeight: 600, border: "none", cursor: "pointer",
                background: viewMode === "chatbot" ? "#1e293b" : "transparent",
                color: viewMode === "chatbot" ? "#38bdf8" : "#94a3b8",
                borderBottom: viewMode === "chatbot" ? "2px solid #38bdf8" : "2px solid transparent",
              }}
            >
              AI Học liệu
            </button>
          </>
        )}
      </div>

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
      ) : viewMode === "qa" ? (
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
                  <div>{a.answer_vi || a.answer_text}</div>
                  {a.answer_en && a.answer_en !== (a.answer_vi || a.answer_text) && (
                    <div style={{ marginTop: 4, fontSize: 12, color: "#94a3b8", fontStyle: "italic" }}>
                      EN: {a.answer_en}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
        </main>
      ) : viewMode === "chatbot" ? (
        <main style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: "12px" }}>
          <form onSubmit={handleAskChatbot} style={{ display: "flex", gap: 8 }}>
            <input
              type="text"
              placeholder="Hỏi về Slide bài giảng hoặc khái niệm vừa học..."
              value={ragInput}
              onChange={(e) => setRagInput(e.target.value)}
              style={{ flex: 1, padding: "9px 12px", borderRadius: 6, border: "1px solid #475569", background: "#0f172a", color: "#fff", fontSize: 13 }}
            />
            <button
              type="submit"
              disabled={askingRag || !ragInput.trim()}
              style={{ background: "#0284c7", color: "#fff", border: "none", borderRadius: 6, padding: "9px 14px", fontWeight: 600, cursor: "pointer" }}
            >
              {askingRag ? "Đang tra..." : "Hỏi AI"}
            </button>
          </form>
          {ragTurns.length === 0 ? (
            <div style={{ textAlign: "center", color: "#64748b", marginTop: 32 }}>
              <p>Trợ lý AI Học liệu (RAG)</p>
              <small>Chỉ trả lời dựa trên Slide PDF & phụ đề buổi học kèm trích dẫn trang. Nếu câu hỏi ngoài phạm vi, bạn có thể chuyển thẳng lên giảng viên.</small>
            </div>
          ) : (
            ragTurns.map((turn) => (
              <div key={turn.message_id} style={{ background: "#1e293b", padding: 12, borderRadius: 8, borderLeft: turn.status === "ANSWERED" ? "3px solid #38bdf8" : "3px solid #f59e0b" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#e2e8f0", marginBottom: 6 }}>Hỏi: {turn.question}</div>
                <div style={{ fontSize: 13, whiteSpace: "pre-line", color: "#cbd5e1", background: "#0f172a", padding: 10, borderRadius: 6 }}>
                  {turn.answer}
                </div>
                {(turn.can_escalate || turn.status === "NO_SOURCE_FOUND") && (
                  <div style={{ marginTop: 8 }}>
                    {turn.escalated ? (
                      <span style={{ fontSize: 12, color: "#6ee7b7" }}>✓ Đã chuyển câu hỏi lên bảng Q&A của giảng viên</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void handleEscalateTurn(turn)}
                        style={{ background: "#b45309", color: "#fff", border: "none", borderRadius: 6, padding: "5px 10px", fontSize: 12, fontWeight: 600, cursor: "pointer" }}
                      >
                        Chuyển câu hỏi cho giảng viên →
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </main>
      ) : (
        <main style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: "14px" }}>
          {quickQuestions.length === 0 ? (
            <div style={{ textAlign: "center", color: "#64748b", marginTop: "40px" }}>
              <p>Giảng viên chưa phát câu hỏi nhanh nào.</p>
              <small>Khi giảng viên tạo Poll / Trắc nghiệm trong buổi học, câu hỏi sẽ xuất hiện tại đây.</small>
            </div>
          ) : (
            quickQuestions.map((q) => {
              const answered = q.myResponse !== null;
              return (
                <div key={q.id} style={{ background: "#1e293b", padding: "14px", borderRadius: "10px", border: "1px solid #334155" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 11, color: "#38bdf8", fontWeight: 700 }}>
                    <span>{q.questionType}</span>
                    {answered && (
                      <span style={{ color: q.myResponse?.isCorrect === false ? "#fca5a5" : "#6ee7b7" }}>
                        {q.myResponse?.isCorrect === true
                          ? "✓ Chính xác"
                          : q.myResponse?.isCorrect === false
                            ? "✗ Chưa đúng"
                            : "✓ Đã nộp"}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>{q.question}</div>

                  {(q.questionType === "POLL" || q.questionType === "MULTIPLE_CHOICE" || q.questionType === "TRUE_FALSE") && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {q.options.map((opt) => (
                        <label
                          key={opt.id}
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 8,
                            padding: "8px 10px",
                            borderRadius: 8,
                            background: "#0f172a",
                            border: opt.isCorrect ? "1px solid #10b981" : "1px solid #334155",
                            cursor: answered ? "default" : "pointer",
                          }}
                        >
                          <input
                            type="radio"
                            name={`qq_${q.id}`}
                            disabled={answered}
                            checked={(answered ? q.myResponse?.selectedOptionId : quizDrafts[q.id]) === opt.id}
                            onChange={() => setQuizDrafts((prev) => ({ ...prev, [q.id]: opt.id }))}
                          />
                          <span>{opt.text}</span>
                        </label>
                      ))}
                    </div>
                  )}

                  {q.questionType === "SHORT_ANSWER" && (
                    <input
                      type="text"
                      disabled={answered}
                      placeholder="Nhập câu trả lời ngắn..."
                      value={answered ? q.myResponse?.answerText ?? "" : quizDrafts[q.id] ?? ""}
                      onChange={(e) => setQuizDrafts((prev) => ({ ...prev, [q.id]: e.target.value }))}
                      style={{ width: "100%", boxSizing: "border-box", padding: "8px 10px", borderRadius: 6, border: "1px solid #475569", background: "#0f172a", color: "#fff" }}
                    />
                  )}

                  {q.questionType === "ORDERING" && (() => {
                    let submittedOrder: string[] | null = null;
                    if (answered && q.myResponse?.answerText) {
                      try {
                        const parsed = JSON.parse(q.myResponse.answerText);
                        if (Array.isArray(parsed)) submittedOrder = parsed.map(String);
                      } catch {
                        submittedOrder = null;
                      }
                    }
                    const itemsOrder: string[] =
                      submittedOrder ?? quizDrafts[q.id] ?? q.options.map((o) => o.text);
                    return (
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {itemsOrder.map((txt: string, idx: number, arr: string[]) => (
                          <div key={idx} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 10px", background: "#0f172a", borderRadius: 6 }}>
                            <span>{idx + 1}. {txt}</span>
                            {!answered && (
                              <div style={{ display: "flex", gap: 4 }}>
                                <button
                                  type="button"
                                  disabled={idx === 0}
                                  onClick={() => {
                                    const next = [...arr];
                                    [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
                                    setQuizDrafts((prev) => ({ ...prev, [q.id]: next }));
                                  }}
                                >↑</button>
                                <button
                                  type="button"
                                  disabled={idx === arr.length - 1}
                                  onClick={() => {
                                    const next = [...arr];
                                    [next[idx + 1], next[idx]] = [next[idx], next[idx + 1]];
                                    setQuizDrafts((prev) => ({ ...prev, [q.id]: next }));
                                  }}
                                >↓</button>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    );
                  })()}

                  {q.questionType === "MATCHING" && (() => {
                    let submittedMap: Record<string, string> | null = null;
                    if (answered && q.myResponse?.answerText) {
                      try {
                        const parsed = JSON.parse(q.myResponse.answerText);
                        if (Array.isArray(parsed)) {
                          submittedMap = {};
                          for (const p of parsed) {
                            if (p && typeof p === "object" && "left" in p && "right" in p) {
                              submittedMap[String(p.left)] = String(p.right);
                            }
                          }
                        }
                      } catch {
                        submittedMap = null;
                      }
                    }
                    const currentMap: Record<string, string> = submittedMap ?? quizDrafts[q.id] ?? {};
                    return (
                      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        {(q.payload.leftItems ?? []).map((left) => (
                          <div key={left} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                            <span style={{ flex: 1, fontSize: 13 }}>{left}</span>
                            <select
                              disabled={answered}
                              value={currentMap[left] ?? ""}
                              onChange={(e) =>
                                setQuizDrafts((prev) => ({
                                  ...prev,
                                  [q.id]: { ...(prev[q.id] ?? {}), [left]: e.target.value },
                                }))
                              }
                              style={{ flex: 1, padding: 6, borderRadius: 6, background: "#0f172a", color: "#fff", border: "1px solid #475569" }}
                            >
                              <option value="">-- Nối với --</option>
                              {(q.payload.rightItems ?? []).map((r) => (
                                <option key={r} value={r}>{r}</option>
                              ))}
                            </select>
                          </div>
                        ))}
                      </div>
                    );
                  })()}

                  {!answered && (
                    <button
                      type="button"
                      disabled={submittingQuizId === q.id}
                      onClick={() => void handleSubmitQuiz(q)}
                      style={{ marginTop: 10, background: "#2563eb", color: "#fff", border: "none", borderRadius: 6, padding: "8px 14px", fontWeight: 600, cursor: "pointer" }}
                    >
                      {submittingQuizId === q.id ? "Đang nộp..." : "Nộp câu trả lời"}
                    </button>
                  )}
                </div>
              );
            })
          )}
        </main>
      )}

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
              transition: "background-color 0.2s",
            }}
          >
            {isSending ? "Đang gửi..." : "Gửi"}
          </button>
        </form>
      </footer>
    </div>
  );
}
