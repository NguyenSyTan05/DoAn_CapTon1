"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "@/lib/router-compat";
import {
  Home,
  BookOpen,
  MessageSquare,
  FileText,
  Settings,
  Radio,
  ArrowLeft,
  X,
  CameraIcon,
  Hash,
} from "lucide-react";
import authService from "../../services/auth.service";
import api from "../../services/api";
import studentService from "../../services/student.service";
import ChangePasswordCard from "../../components/shell/ChangePasswordCard";
import styles from "./home.module.css";

type ClassItem = {
  id: string;
  code: string;
  name: string;
  lecturerName: string;
  status: "ongoing" | "upcoming";
  liveSession: { id: string; title: string; startedAt: string | null } | null;
  nextStartTime: string | null;
  nextSession: { id: string; title: string; startTime: string | null; endTime: string | null } | null;
};

type JoinScreen = "none" | "scanQr" | "enterCode";
type SidebarSection = "home" | "my-class" | "live-lessons" | "question" | "setting";

const NAV_ITEMS: Array<{
  id: SidebarSection | "summary";
  label: string;
  icon: typeof Home;
}> = [
  { id: "home", label: "Trang chủ", icon: Home },
  { id: "my-class", label: "Lớp của tôi", icon: BookOpen },
  { id: "live-lessons", label: "Buổi học trực tiếp", icon: Radio },
  { id: "question", label: "Hỏi đáp Q&A", icon: MessageSquare },
  { id: "summary", label: "Tóm tắt bài giảng", icon: FileText },
];

const formatDateTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("vi-VN", {
        hour: "2-digit",
        minute: "2-digit",
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      })
    : "";

const waitingText = (s: { startTime: string | null; endTime: string | null }) => {
  if (!s.startTime) return "Đã lên lịch · chờ giảng viên bắt đầu";
  const now = Date.now();
  const start = new Date(s.startTime).getTime();
  const end = s.endTime ? new Date(s.endTime).getTime() : Infinity;
  const range = `${formatDateTime(s.startTime)}${s.endTime ? ` – ${formatDateTime(s.endTime)}` : ""}`;
  return now >= start && now <= end
    ? `Đã đến giờ (${range}) · chờ giảng viên bắt đầu`
    : `Buổi tới: ${range}`;
};

function extractClassCodeFromRaw(raw: string): string {
  const trimmed = raw.trim();
  try {
    const parsed = new URL(trimmed);
    const fromParam = parsed.searchParams.get("joinCode") || parsed.searchParams.get("code");
    if (fromParam) return fromParam.trim().toUpperCase();
  } catch {
    /* chuỗi mã lớp thuần */
  }
  return trimmed.toUpperCase();
}

export default function StudentHome() {
  const navigate = useNavigate();
  useLocation();

  const user = authService.getCurrentUser();
  const studentName: string = user?.full_name || "";
  const initial = studentName.trim().charAt(0).toUpperCase() || "?";

  const [activeSection, setActiveSection] = useState<SidebarSection>("home");
  const [activeTab, setActiveTab] = useState<"ongoing" | "upcoming">("ongoing");
  const [joinScreen, setJoinScreen] = useState<JoinScreen>("none");
  const [classCodeInput, setClassCodeInput] = useState("");
  const [notice, setNotice] = useState("");
  const [joinError, setJoinError] = useState("");
  const [joining, setJoining] = useState(false);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [classesError, setClassesError] = useState("");
  const [classesNotice, setClassesNotice] = useState("");
  const [showNotifPanel, setShowNotifPanel] = useState(false);
  const [subtitlePref, setSubtitlePref] = useState<"both" | "vi" | "en">("both");

  // Camera quét QR trực tiếp bằng BarcodeDetector
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const qrStreamRef = useRef<MediaStream | null>(null);
  const [cameraActive, setCameraActive] = useState(false);

  const stopQrCamera = useCallback(() => {
    qrStreamRef.current?.getTracks().forEach((t) => t.stop());
    qrStreamRef.current = null;
    setCameraActive(false);
  }, []);

  const loadClasses = useCallback(async () => {
    try {
      setClasses(await studentService.getMyClasses());
      setClassesError("");
    } catch {
      setClassesError("Không tải được danh sách lớp. Vui lòng thử lại.");
    }
  }, []);

  const joinWithCodeString = useCallback(
    async (rawCode: string) => {
      const code = extractClassCodeFromRaw(rawCode);
      if (!code || joining) return;
      setJoining(true);
      setJoinError("");
      try {
        const result = await studentService.joinClassByCode(code);
        stopQrCamera();
        setClassCodeInput("");
        if (result.session?.id) {
          navigate(`/room?session=${encodeURIComponent(result.session.id)}`);
          return;
        }
        await loadClasses();
        setActiveTab("upcoming");
        setJoinScreen("none");
        setClassesNotice(
          `Đã tham gia lớp ${result.class?.name ?? code}. Hiện chưa có buổi học nào sắp diễn ra.`,
        );
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { message?: string } } })?.response?.data?.message ||
          "Không thể tham gia lớp với mã này. Vui lòng kiểm tra lại.";
        setJoinError(msg);
      } finally {
        setJoining(false);
      }
    },
    [joining, loadClasses, navigate, stopQrCamera],
  );

  useEffect(() => {
    void loadClasses();
    const savedPref = localStorage.getItem("student_subtitle_pref");
    if (savedPref === "both" || savedPref === "vi" || savedPref === "en") {
      const t = window.setTimeout(() => setSubtitlePref(savedPref), 0);
      return () => window.clearTimeout(t);
    }
  }, [loadClasses]);

  // Hỗ trợ quét QR từ camera điện thoại mở thẳng ?joinCode=MÃ_LỚP
  useEffect(() => {
    if (typeof window === "undefined") return;
    const joinParam = new URLSearchParams(window.location.search).get("joinCode");
    if (joinParam) {
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, "", cleanUrl);
      const t = window.setTimeout(() => {
        void joinWithCodeString(joinParam);
      }, 0);
      return () => window.clearTimeout(t);
    }
  }, [joinWithCodeString]);

  useEffect(() => {
    return () => stopQrCamera();
  }, [stopQrCamera]);

  const startQrCamera = async () => {
    setNotice("");
    setJoinError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      qrStreamRef.current = stream;
      setCameraActive(true);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      const BarcodeDetectorCtor = (window as unknown as {
        BarcodeDetector?: new (opts: { formats: string[] }) => {
          detect: (src: HTMLVideoElement) => Promise<Array<{ rawValue?: string }>>;
        };
      }).BarcodeDetector;

      if (!BarcodeDetectorCtor) {
        setNotice(
          "Trình duyệt này không hỗ trợ giải mã QR trực tiếp — hãy dán đường dẫn hoặc mã lớp vào ô bên dưới.",
        );
        return;
      }

      const detector = new BarcodeDetectorCtor({ formats: ["qr_code"] });
      const scanLoop = async () => {
        if (!qrStreamRef.current || !videoRef.current) return;
        try {
          const codes = await detector.detect(videoRef.current);
          if (codes[0]?.rawValue) {
            await joinWithCodeString(codes[0].rawValue);
            return;
          }
        } catch {
          /* tiếp tục quét */
        }
        if (qrStreamRef.current) {
          requestAnimationFrame(() => void scanLoop());
        }
      };
      requestAnimationFrame(() => void scanLoop());
    } catch {
      setNotice("Không mở được camera. Hãy cấp quyền camera hoặc nhập mã lớp ở ô bên dưới.");
    }
  };

  const ongoingClasses = classes.filter((c) => c.status === "ongoing");
  const upcomingClasses = classes.filter((c) => c.status === "upcoming");
  const visibleClasses = activeTab === "ongoing" ? ongoingClasses : upcomingClasses;

  const handleLogout = async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* ignore */
    }
    authService.logout();
    navigate("/login", { replace: true });
  };

  const closeJoin = () => {
    stopQrCamera();
    setNotice("");
    setJoinError("");
    setJoinScreen("none");
  };

  const handleSidebarClick = (id: SidebarSection | "summary") => {
    if (id === "summary") {
      navigate("/summary");
      return;
    }
    setActiveSection(id);
    if (id === "live-lessons") setActiveTab("ongoing");
    if (id === "my-class") {
      document.getElementById("my-classes-box")?.scrollIntoView({ behavior: "smooth" });
    }
  };

  if (joinScreen === "scanQr") {
    return (
      <div className={styles.page}>
        <div className={styles.joinScreen}>
          <button className={styles.backButton} onClick={closeJoin}>
            <ArrowLeft size={18} /> Quay lại
          </button>
          <h1 className={styles.joinScreenTitle}>Quét mã QR lớp học</h1>
          <div className={styles.scanBox} style={{ position: "relative", overflow: "hidden" }}>
            <span className={`${styles.scanCorner} ${styles.scanCornerTL}`} />
            <span className={`${styles.scanCorner} ${styles.scanCornerTR}`} />
            <span className={`${styles.scanCorner} ${styles.scanCornerBL}`} />
            <span className={`${styles.scanCorner} ${styles.scanCornerBR}`} />
            {cameraActive ? (
              <video
                ref={videoRef}
                muted
                playsInline
                style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: 12 }}
              />
            ) : (
              <button
                type="button"
                className={styles.scanCameraCircle}
                onClick={() => void startQrCamera()}
                aria-label="Bật camera quét mã QR"
                style={{ border: "none", cursor: "pointer" }}
              >
                <CameraIcon />
              </button>
            )}
          </div>
          <p className={styles.scanHint}>
            {cameraActive ? "Đang quét mã QR từ màn chiếu giảng viên..." : "Bấm biểu tượng máy ảnh để bật camera quét QR"}
          </p>
          <div style={{ display: "flex", gap: 8, maxWidth: 360, width: "100%", marginTop: 12 }}>
            <input
              type="text"
              placeholder="Hoặc dán link QR / mã lớp..."
              value={classCodeInput}
              onChange={(e) => setClassCodeInput(e.target.value)}
              style={{ flex: 1, padding: "9px 12px", borderRadius: 8, border: "1px solid #cbd5e1" }}
            />
            <button
              type="button"
              className={styles.joinBtn}
              disabled={!classCodeInput.trim() || joining}
              onClick={() => void joinWithCodeString(classCodeInput)}
            >
              Vào lớp
            </button>
          </div>
          {notice && <p className={styles.noticeText}>{notice}</p>}
          {joinError && <p className={styles.errorText} role="alert">{joinError}</p>}
        </div>
      </div>
    );
  }

  if (joinScreen === "enterCode") {
    return (
      <div className={styles.page}>
        <div className={styles.joinScreen}>
          <div className={styles.modalCard}>
            <div className={styles.modalTopBar}>
              <button
                type="button"
                className={styles.modalTopBarBrand}
                onClick={() => navigate("/")}
                aria-label="Về trang chủ"
              >
                <img src="/Ai.png" alt="Logo" className={styles.modalTopBarLogo} /> ClassBridge
              </button>
              <button className={styles.modalCloseBtn} onClick={closeJoin}>
                <X size={16} />
              </button>
            </div>

            <h1 className={styles.modalTitle}>Nhập mã lớp</h1>

            <div className={styles.selectField}>
              <Hash size={16} className={styles.selectFieldIcon} />
              <input
                type="text"
                className={styles.selectFieldInput}
                placeholder="Nhập mã lớp học"
                value={classCodeInput}
                onChange={(e) => {
                  setClassCodeInput(e.target.value.toUpperCase());
                  setJoinError("");
                }}
                onKeyDown={(e) => e.key === "Enter" && void joinWithCodeString(classCodeInput)}
                maxLength={80}
              />
            </div>

            <div className={styles.modalActions}>
              <button className={styles.cancelBtn} onClick={closeJoin}>
                Hủy
              </button>
              <button
                className={styles.joinBtn}
                disabled={!classCodeInput.trim() || joining}
                onClick={() => void joinWithCodeString(classCodeInput)}
              >
                {joining ? "Đang tham gia..." : "Tham gia"}
              </button>
            </div>
            {joinError && <p className={styles.errorText} role="alert">{joinError}</p>}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.topbar}>
        <div className={styles.logoArea}>
          <button
            type="button"
            className={styles.logoText}
            onClick={() => navigate("/")}
            aria-label="Về trang chủ"
          >
            <img src="/logoclass-transparent.png" alt="Logo" /> ClassBridge
          </button>
        </div>

        <div className={styles.topbarActions} style={{ position: "relative" }}>
          <button
            type="button"
            className={styles.bellButton}
            aria-label="Thông báo"
            onClick={() => setShowNotifPanel((v) => !v)}
          >
            🔔{ongoingClasses.length > 0 ? ` (${ongoingClasses.length})` : ""}
          </button>
          {showNotifPanel && (
            <div
              style={{
                position: "absolute",
                top: "110%",
                right: 120,
                width: 290,
                background: "#fff",
                color: "#0f172a",
                border: "1px solid #e2e8f0",
                borderRadius: 12,
                padding: 12,
                boxShadow: "0 10px 25px rgba(15,23,42,0.12)",
                zIndex: 40,
              }}
            >
              <strong style={{ fontSize: 13 }}>Thông báo lớp học</strong>
              {ongoingClasses.length === 0 ? (
                <p style={{ margin: "8px 0 0", fontSize: 12.5, color: "#64748b" }}>
                  Chưa có buổi học nào đang diễn ra trực tiếp.
                </p>
              ) : (
                ongoingClasses.map((c) => (
                  <div
                    key={c.id}
                    style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid #f1f5f9", fontSize: 12.5 }}
                  >
                    <div style={{ fontWeight: 600 }}>{c.name}</div>
                    <button
                      type="button"
                      onClick={() =>
                        c.liveSession &&
                        navigate(`/room?session=${encodeURIComponent(c.liveSession.id)}`)
                      }
                      style={{ marginTop: 4, background: "#2563eb", color: "#fff", border: "none", borderRadius: 6, padding: "4px 10px", fontSize: 12, cursor: "pointer" }}
                    >
                      Vào phòng ngay
                    </button>
                  </div>
                ))
              )}
            </div>
          )}
          <span className={styles.userLabel} title="Tài khoản đang đăng nhập">
            Sinh viên: {studentName || "—"}
          </span>
          <div className={styles.avatar} title={studentName}>{initial}</div>
          <button className={styles.logoutBtn} onClick={handleLogout}>
            Đăng xuất
          </button>
        </div>
      </header>

      <div className={styles.body}>
        <aside className={styles.sidebar}>
          <nav className={styles.navMenu}>
            {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => handleSidebarClick(id)}
                className={`${styles.navItem} ${activeSection === id ? styles.navItemActive : ""}`}
              >
                <Icon size={18} />
                <span>{label}</span>
              </button>
            ))}
            <div className={styles.sidebarDivider}>
              <button
                type="button"
                onClick={() => setActiveSection("setting")}
                className={`${styles.navItem} ${activeSection === "setting" ? styles.navItemActive : ""}`}
              >
                <Settings size={18} />
                <span>Cài đặt</span>
              </button>
            </div>
          </nav>
        </aside>

        <main className={styles.main}>
          <h1 className={styles.greetingTitle}>Xin chào, {studentName}!</h1>
          <p className={styles.greetingSubtitle}>
            Tham gia lớp học để theo dõi phụ đề song ngữ, đặt câu hỏi ẩn danh và xem tóm tắt bài giảng AI.
          </p>

          {activeSection === "setting" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 18, marginBottom: 22 }}>
              <div className={styles.classBox}>
                <h2 className={styles.sectionTitle}>Cài đặt hiển thị học tập</h2>
                <label style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 14, marginTop: 10 }}>
                  <span>Chế độ phụ đề ưu tiên:</span>
                  <select
                    value={subtitlePref}
                    onChange={(e) => {
                      const val = e.target.value as "both" | "vi" | "en";
                      setSubtitlePref(val);
                      localStorage.setItem("student_subtitle_pref", val);
                    }}
                    style={{ padding: "7px 12px", borderRadius: 8, border: "1px solid #cbd5e1" }}
                  >
                    <option value="both">Song ngữ Anh + Việt</option>
                    <option value="vi">Ưu tiên Tiếng Việt</option>
                    <option value="en">Ưu tiên Tiếng Anh</option>
                  </select>
                </label>
              </div>

              <ChangePasswordCard maxWidth="100%" />
            </div>
          )}

          {activeSection === "question" && (
            <div className={styles.classBox} style={{ marginBottom: 22 }}>
              <h2 className={styles.sectionTitle}>Hỏi đáp ẩn danh & Câu hỏi nhanh</h2>
              <p style={{ fontSize: 14, color: "#475569", margin: "6px 0 12px" }}>
                Chọn một buổi học đang diễn ra để đặt câu hỏi ẩn danh trên di động/máy tính hoặc trả lời Quiz nhanh của giảng viên:
              </p>
              {ongoingClasses.length === 0 ? (
                <p className={styles.emptyText}>Hiện chưa có lớp nào đang phát trực tiếp. Bạn vẫn có thể xem lại câu trả lời ở mục Tóm tắt bài giảng.</p>
              ) : (
                ongoingClasses.map((c) => (
                  <div key={c.id} className={styles.classCard}>
                    <div className={styles.classInfo}>
                      <div className={styles.classTitle}>{c.code} - {c.name}</div>
                      <div className={styles.classInstructor}>{c.liveSession?.title}</div>
                    </div>
                    {c.liveSession && (
                      <button
                        type="button"
                        className={styles.joinClassBtn}
                        onClick={() => navigate(`/sinhvien/classroom/${encodeURIComponent(c.liveSession!.id)}`)}
                      >
                        Mở Q&A & Quiz
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
          )}

          <h2 className={styles.sectionTitle}>Tham gia lớp học</h2>
          <div className={styles.joinGrid}>
            <button className={styles.joinCardPrimary} onClick={() => setJoinScreen("scanQr")}>
              <span className={styles.joinIconWrap}>
                <CameraIcon />
              </span>
              <div className={styles.joinTitle}>Quét mã QR</div>
              <div className={styles.joinSubtitle}>Dùng camera quét mã lớp từ màn chiếu</div>
            </button>

            <button className={styles.joinCard} onClick={() => setJoinScreen("enterCode")}>
              <span className={styles.joinIconWrap}>
                <Hash />
              </span>
              <div className={styles.joinTitle}>Nhập mã lớp</div>
              <div className={styles.joinSubtitle}>Nhập mã lớp do giảng viên cung cấp</div>
            </button>
          </div>

          <div id="my-classes-box" className={styles.classBox}>
            <div className={styles.classBoxHeader} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              <h2 className={styles.sectionTitle}>Các lớp học của tôi</h2>
              <button
                type="button"
                className={styles.joinClassBtn}
                onClick={() => navigate("/summary")}
              >
                Xem Tóm tắt bài giảng AI
              </button>
            </div>

            <div className={styles.tabs}>
              <button
                className={`${styles.tab} ${activeTab === "ongoing" ? styles.tabActive : ""}`}
                onClick={() => setActiveTab("ongoing")}
              >
                Đang diễn ra ({ongoingClasses.length})
              </button>
              <button
                className={`${styles.tab} ${activeTab === "upcoming" ? styles.tabActive : ""}`}
                onClick={() => setActiveTab("upcoming")}
              >
                Sắp tới ({upcomingClasses.length})
              </button>
            </div>

            {classesNotice && <p className={styles.noticeText}>{classesNotice}</p>}
            {classesError && <p className={styles.errorText} role="alert">{classesError}</p>}
            {!classesError && visibleClasses.length === 0 && (
              <p className={styles.emptyText}>
                {classes.length === 0
                  ? "Bạn chưa tham gia lớp nào. Hãy nhập mã lớp hoặc quét mã QR do giảng viên cung cấp."
                  : "Không có lớp nào ở mục này."}
              </p>
            )}

            {visibleClasses.map((c) => (
              <div key={c.id} className={styles.classCard}>
                <span className={styles.classIcon}>📘</span>
                <div className={styles.classInfo}>
                  <div className={styles.classTitle}>
                    {c.code} - {c.name}
                  </div>
                  <div className={styles.classInstructor}>{c.lecturerName}</div>
                  <div className={styles.classMeta}>
                    {c.liveSession
                      ? `Đang học: ${c.liveSession.title}`
                      : c.nextSession
                        ? waitingText(c.nextSession)
                        : "Chưa có buổi học sắp diễn ra"}
                  </div>
                </div>
                {!c.liveSession && c.nextSession && (
                  <button
                    type="button"
                    className={styles.joinClassBtn}
                    onClick={() => navigate(`/room?session=${encodeURIComponent(c.nextSession!.id)}`)}
                  >
                    Vào phòng chờ
                  </button>
                )}
                {c.liveSession && (
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className={styles.joinClassBtn}
                      onClick={() => navigate(`/room?session=${encodeURIComponent(c.liveSession!.id)}`)}
                    >
                      Vào lớp (PC)
                    </button>
                    <button
                      type="button"
                      className={styles.joinClassBtn}
                      style={{ background: "#0f766e" }}
                      onClick={() => navigate(`/sinhvien/classroom/${encodeURIComponent(c.liveSession!.id)}`)}
                    >
                      Mobile & Quiz
                    </button>
                  </div>
                )}
                <span
                  className={c.status === "ongoing" ? styles.statusOngoing : styles.statusUpcoming}
                >
                  {c.status === "ongoing" ? "Đang diễn ra" : "Sắp diễn ra"}
                </span>
              </div>
            ))}
          </div>
        </main>
      </div>
    </div>
  );
}
