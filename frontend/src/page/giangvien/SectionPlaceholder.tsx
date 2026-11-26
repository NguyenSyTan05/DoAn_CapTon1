"use client";

import React, { useEffect, useState } from "react";
import { notFound, useParams, useRouter } from "next/navigation";
import { ExternalLink, Layers, MessageSquare, Reply, Save, Sparkles } from "lucide-react";
import LecturerLayout from "./layoutGV";
import LessonSummaryPage from "../summary/LessonSummaryPage";
import ChangePasswordCard from "../../components/shell/ChangePasswordCard";
import api from "../../services/api";
import { aiFetch } from "../../lib/ai";

type SessionRow = {
  id: string;
  title: string;
  status: string;
  classCode: string;
  className: string;
  startedAt: string | null;
};

const SECTIONS: Record<string, { title: string; description: string }> = {
  sessions: { title: "Classroom Sessions", description: "Danh sách và trạng thái các phiên học của giảng viên." },
  qna: { title: "Anonymous Q&A", description: "Theo dõi câu hỏi ẩn danh của sinh viên theo từng phiên học." },
  question: { title: "Question Clusters", description: "Các nhóm câu hỏi tương đồng ngữ nghĩa được AI gom theo chủ đề." },
  clusters: { title: "Question Clusters", description: "Các nhóm câu hỏi tương đồng ngữ nghĩa được AI gom theo chủ đề." },
  answers: { title: "Kho câu trả lời", description: "Quản lý câu trả lời đại diện đã phát cho sinh viên theo từng phiên." },
  summary: { title: "Session Summary & Heatmap", description: "Tóm tắt bài giảng và bản đồ nhiệt tương tác của lớp." },
  profile: { title: "Hồ sơ cá nhân", description: "Cập nhật thông tin tài khoản và tùy chọn ngôn ngữ của giảng viên." },
};

function LecturerProfileSection() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [department, setDepartment] = useState("");
  const [preferredLanguage, setPreferredLanguage] = useState("vi");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    let active = true;
    api
      .get("/auth/lecturer/profile")
      .then(({ data }) => {
        if (!active || !data?.profile) return;
        setFullName(data.profile.fullName || "");
        setEmail(data.profile.email || "");
        setPhone(data.profile.phone || "");
        setDepartment(data.profile.department || "");
        setPreferredLanguage(data.profile.preferredLanguage || "vi");
      })
      .catch(() => {
        if (active) setErr("Không thể tải hồ sơ cá nhân.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMsg("");
    setErr("");
    try {
      const { data } = await api.patch("/auth/lecturer/profile", {
        fullName,
        phone,
        department,
        preferredLanguage,
      });
      setMsg(data.message || "Đã cập nhật hồ sơ thành công.");
      try {
        const stored = JSON.parse(localStorage.getItem("user") || "{}");
        localStorage.setItem("user", JSON.stringify({ ...stored, full_name: fullName }));
      } catch {
        /* ignore */
      }
    } catch {
      setErr("Không thể lưu hồ sơ. Vui lòng kiểm tra lại số điện thoại hoặc kết nối.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <main style={{ flex: 1, minWidth: 0, padding: "28px 32px", background: "#f4f6fb", color: "#0f172a" }}>
      <h1 style={{ margin: "0 0 6px", fontSize: 24 }}>Hồ sơ cá nhân Giảng viên</h1>
      <p style={{ margin: "0 0 20px", color: "#64748b" }}>Quản lý thông tin hiển thị trên lớp học và ngôn ngữ ưu tiên.</p>

      <form
        onSubmit={handleSubmit}
        style={{
          maxWidth: 620,
          background: "#fff",
          border: "1px solid #e2e8f0",
          borderRadius: 14,
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 14,
        }}
      >
        {loading ? (
          <p>Đang tải thông tin...</p>
        ) : (
          <>
            {msg && <div style={{ padding: "10px 12px", borderRadius: 8, background: "#ecfdf5", color: "#047857", fontSize: 13 }}>{msg}</div>}
            {err && <div style={{ padding: "10px 12px", borderRadius: 8, background: "#fef2f2", color: "#b91c1c", fontSize: 13 }}>{err}</div>}
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600 }}>
              Email đăng nhập (không thay đổi)
              <input value={email} disabled style={{ padding: "9px 12px", borderRadius: 8, border: "1px solid #e2e8f0", background: "#f1f5f9", color: "#64748b" }} />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600 }}>
              Họ và tên giảng viên
              <input value={fullName} onChange={(e) => setFullName(e.target.value)} required maxLength={100} style={{ padding: "9px 12px", borderRadius: 8, border: "1px solid #cbd5e1" }} />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600 }}>
              Số điện thoại
              <input value={phone} onChange={(e) => setPhone(e.target.value)} maxLength={30} placeholder="VD: 0905123456" style={{ padding: "9px 12px", borderRadius: 8, border: "1px solid #cbd5e1" }} />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600 }}>
              Khoa / Bộ môn
              <input value={department} onChange={(e) => setDepartment(e.target.value)} maxLength={150} placeholder="VD: Khoa Kỹ thuật Phần mềm - Trường Quốc tế" style={{ padding: "9px 12px", borderRadius: 8, border: "1px solid #cbd5e1" }} />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600 }}>
              Ngôn ngữ giao diện ưu tiên
              <select value={preferredLanguage} onChange={(e) => setPreferredLanguage(e.target.value)} style={{ padding: "9px 12px", borderRadius: 8, border: "1px solid #cbd5e1" }}>
                <option value="vi">Tiếng Việt</option>
                <option value="en">English</option>
              </select>
            </label>
            <button
              type="submit"
              disabled={saving}
              style={{ alignSelf: "flex-start", display: "inline-flex", alignItems: "center", gap: 8, background: "#2563eb", color: "#fff", border: "none", borderRadius: 10, padding: "10px 18px", fontWeight: 600, cursor: "pointer" }}
            >
              <Save size={16} /> {saving ? "Đang lưu..." : "Lưu thay đổi"}
            </button>
          </>
        )}
      </form>

      <div style={{ marginTop: 22 }}>
        <ChangePasswordCard maxWidth={620} />
      </div>
    </main>
  );
}

export default function SectionPlaceholder() {
  const { section } = useParams<{ section: string }>();
  const router = useRouter();
  const info = SECTIONS[section];
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [questions, setQuestions] = useState<Array<{ id: string; text: string; timestamp: string }>>([]);
  const [answers, setAnswers] = useState<Array<{ representative_id: string; representative_text: string; total_count: number; answer_text: string }>>([]);
  const [loadingHub, setLoadingHub] = useState(true);

  useEffect(() => {
    if (!info || section === "summary" || section === "profile") return;
    let active = true;
    api
      .get<{ sessions: SessionRow[] }>("/auth/summaries/sessions")
      .then(({ data }) => {
        if (!active) return;
        const list = data.sessions ?? [];
        setSessions(list);
        if (list[0]?.id) setSelectedId(list[0].id);
      })
      .catch(() => {})
      .finally(() => {
        if (active) setLoadingHub(false);
      });
    return () => {
      active = false;
    };
  }, [info, section]);

  useEffect(() => {
    if (!selectedId || section === "summary" || section === "profile" || section === "sessions") return;
    let active = true;
    Promise.all([
      aiFetch(`/api/v1/questions?session=${encodeURIComponent(selectedId)}`),
      aiFetch(`/api/v1/answers?session=${encodeURIComponent(selectedId)}`),
    ])
      .then(async ([qRes, aRes]) => {
        if (!active) return;
        if (qRes.ok) {
          const qData = await qRes.json();
          setQuestions(qData.questions ?? []);
        }
        if (aRes.ok) {
          const aData = await aRes.json();
          setAnswers(aData.answers ?? []);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [selectedId, section]);

  if (!info) notFound();

  if (section === "summary") {
    return (
      <LecturerLayout>
        <LessonSummaryPage mode="lecturer" />
      </LecturerLayout>
    );
  }

  if (section === "profile") {
    return (
      <LecturerLayout>
        <LecturerProfileSection />
      </LecturerLayout>
    );
  }

  return (
    <LecturerLayout>
      <main style={{ flex: 1, minWidth: 0, padding: "28px 32px", background: "#f4f6fb", color: "#0f172a" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 14, marginBottom: 20 }}>
          <div>
            <h1 style={{ margin: "0 0 6px", fontSize: 24 }}>{info.title}</h1>
            <p style={{ margin: 0, color: "#64748b" }}>{info.description}</p>
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <select
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              style={{ padding: "9px 12px", borderRadius: 10, border: "1px solid #cbd5e1", background: "#fff", minWidth: 250 }}
            >
              {sessions.length === 0 && <option value="">Chưa có phiên học</option>}
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  [{s.status}] {s.classCode} — {s.title}
                </option>
              ))}
            </select>
            {selectedId && (
              <>
                <button
                  type="button"
                  onClick={() => window.open(`/dashboard/teacher?session=${encodeURIComponent(selectedId)}`, "_blank")}
                  style={{ display: "inline-flex", alignItems: "center", gap: 7, background: "#2563eb", color: "#fff", border: "none", borderRadius: 10, padding: "9px 15px", fontWeight: 600, cursor: "pointer" }}
                >
                  <ExternalLink size={15} /> Mở Bảng điều phối AI Q&A
                </button>
                <button
                  type="button"
                  onClick={() => router.push(`/giangvien/summary?session=${encodeURIComponent(selectedId)}`)}
                  style={{ display: "inline-flex", alignItems: "center", gap: 7, background: "#fff", color: "#1e293b", border: "1px solid #cbd5e1", borderRadius: 10, padding: "9px 14px", fontWeight: 600, cursor: "pointer" }}
                >
                  <Sparkles size={15} /> Xem Tóm tắt & Heatmap
                </button>
              </>
            )}
          </div>
        </div>

        {loadingHub ? (
          <div style={{ background: "#fff", padding: 20, borderRadius: 14, border: "1px solid #e2e8f0" }}>Đang tải dữ liệu phiên học...</div>
        ) : sessions.length === 0 ? (
          <div style={{ background: "#fff", padding: 20, borderRadius: 14, border: "1px solid #e2e8f0" }}>
            Chưa có phiên học nào. Hãy tạo lớp tại mục <strong>My Classes</strong> trước.
          </div>
        ) : section === "answers" ? (
          <section style={{ background: "#fff", padding: 22, borderRadius: 14, border: "1px solid #e2e8f0" }}>
            <h3 style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 8 }}>
              <Reply size={18} color="#16a34a" /> Câu trả lời đã gửi trong phiên ({answers.length})
            </h3>
            {answers.length === 0 ? (
              <p style={{ color: "#64748b" }}>Chưa có câu trả lời nào trong phiên học này. Mở Bảng điều phối AI Q&A để gom cụm và trả lời câu hỏi đại diện.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {answers.map((a) => (
                  <div key={a.representative_id} style={{ border: "1px solid #e2e8f0", borderRadius: 10, padding: 14, background: "#f8fafc" }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: "#2563eb", marginBottom: 4 }}>{a.total_count} sinh viên hỏi tương tự</div>
                    <div style={{ fontWeight: 600, marginBottom: 6 }}>“{a.representative_text}”</div>
                    <div style={{ background: "#ecfdf5", color: "#065f46", padding: "8px 12px", borderRadius: 8 }}>{a.answer_text}</div>
                  </div>
                ))}
              </div>
            )}
          </section>
        ) : (
          <section style={{ background: "#fff", padding: 22, borderRadius: 14, border: "1px solid #e2e8f0" }}>
            <h3 style={{ marginTop: 0, display: "flex", alignItems: "center", gap: 8 }}>
              {section === "qna" ? <MessageSquare size={18} color="#2563eb" /> : <Layers size={18} color="#7c3aed" />}
              Danh sách câu hỏi ẩn danh của phiên ({questions.length})
            </h3>
            {questions.length === 0 ? (
              <p style={{ color: "#64748b" }}>Chưa có câu hỏi nào từ sinh viên trong phiên học này.</p>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {questions.map((q) => (
                  <div key={q.id} style={{ border: "1px solid #e2e8f0", borderRadius: 10, padding: "10px 14px", display: "flex", justifyContent: "space-between", gap: 12 }}>
                    <span>{q.text}</span>
                    <small style={{ color: "#64748b", whiteSpace: "nowrap" }}>{q.timestamp.slice(11, 19)}</small>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </main>
    </LecturerLayout>
  );
}
