"use client";

import { useCallback, useEffect, useState } from "react";
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
import styles from "./home.module.css";

// Trang chủ sinh viên (giao diện lấy từ /sinhvien/app/home).
// Các trang khác trong sidebar chưa được ghép nên tạm khóa.

type ClassItem = {
  id: string;
  code: string;
  name: string;
  lecturerName: string;
  status: "ongoing" | "upcoming";
  liveSession: { id: string; title: string; startedAt: string | null } | null;
  nextStartTime: string | null;
  // Buổi đã lên lịch nhưng giảng viên chưa bấm bắt đầu -> vào "phòng chờ"
  nextSession: { id: string; title: string; startTime: string | null; endTime: string | null } | null;
};

type JoinScreen = "none" | "scanQr" | "enterCode";

const NAV_ITEMS = [
  { label: "Home", href: "/sinhvien", icon: Home, ready: true },
  { label: "My class", href: "/my-class", icon: BookOpen, ready: false },
  { label: "Live lessons", href: "/live-lession", icon: Radio, ready: false },
  { label: "Question grouping", href: "/question", icon: MessageSquare, ready: false },
  { label: "Lesson Summary", href: "/summary", icon: FileText, ready: false },
];

const SETTING_NAV_ITEM = { label: "Setting", href: "/setting", icon: Settings, ready: false };

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

const QR_NOTICE = "Tham gia bằng mã QR sẽ được bổ sung sau. Hiện bạn hãy dùng mã lớp.";

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

export default function StudentHome() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const user = authService.getCurrentUser();
  const studentName: string = user?.full_name || "";
  const initial = studentName.trim().charAt(0).toUpperCase() || "?";

  const [activeTab, setActiveTab] = useState<"ongoing" | "upcoming">("ongoing");
  const [joinScreen, setJoinScreen] = useState<JoinScreen>("none");
  const [classCodeInput, setClassCodeInput] = useState("");
  const [notice, setNotice] = useState("");
  const [joinError, setJoinError] = useState("");
  const [joining, setJoining] = useState(false);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [classesError, setClassesError] = useState("");
  const [classesNotice, setClassesNotice] = useState("");

  const loadClasses = useCallback(async () => {
    try {
      setClasses(await studentService.getMyClasses());
      setClassesError("");
    } catch {
      setClassesError("Không tải được danh sách lớp. Vui lòng thử lại.");
    }
  }, []);

  useEffect(() => {
    void loadClasses();
  }, [loadClasses]);

  const handleJoinByCode = async () => {
    const code = classCodeInput.trim();
    if (!code || joining) return;
    setJoining(true);
    setJoinError("");
    try {
      const result = await studentService.joinClassByCode(code);
      setClassCodeInput("");
      if (result.session?.id) {
        navigate(`/room?session=${encodeURIComponent(result.session.id)}`);
        return;
      }
      await loadClasses();
      setActiveTab("upcoming");
      setJoinScreen("none");
      setClassesNotice(
        `Đã tham gia lớp ${result.class?.name ?? ""}. Hiện chưa có buổi học nào sắp diễn ra.`,
      );
    } catch (err: any) {
      setJoinError(
        err.response?.data?.message ||
          (err.response ? "Không thể tham gia lớp. Vui lòng thử lại." : "Không kết nối được máy chủ."),
      );
    } finally {
      setJoining(false);
    }
  };

  const ongoingClasses = classes.filter((c) => c.status === "ongoing");
  const upcomingClasses = classes.filter((c) => c.status === "upcoming");
  const visibleClasses = activeTab === "ongoing" ? ongoingClasses : upcomingClasses;

  const handleLogout = async () => {
    try {
      await api.post("/auth/logout"); // ghi audit log, lỗi cũng bỏ qua
    } catch {
      /* ignore */
    }
    authService.logout();
    navigate("/login", { replace: true });
  };

  const closeJoin = () => {
    setNotice("");
    setJoinError("");
    setJoinScreen("none");
  };

  if (joinScreen === "scanQr") {
    return (
      <div className={styles.page}>
        <div className={styles.joinScreen}>
          <button className={styles.backButton} onClick={closeJoin}>
            <ArrowLeft size={18} /> Quay lại
          </button>
          <h1 className={styles.joinScreenTitle}>Quét mã QR</h1>
          <div className={styles.scanBox}>
            <span className={`${styles.scanCorner} ${styles.scanCornerTL}`} />
            <span className={`${styles.scanCorner} ${styles.scanCornerTR}`} />
            <span className={`${styles.scanCorner} ${styles.scanCornerBL}`} />
            <span className={`${styles.scanCorner} ${styles.scanCornerBR}`} />
            <button
              type="button"
              className={styles.scanCameraCircle}
              onClick={() => setNotice(QR_NOTICE)}
              aria-label="Quét mã QR"
              style={{ border: "none", cursor: "pointer" }}
            >
              <CameraIcon />
            </button>
          </div>
          <p className={styles.scanHint}>Đưa mã QR vào khung hình</p>
          {notice && <p className={styles.noticeText}>{notice}</p>}
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
              <span className={styles.modalTopBarBrand}>
                <img src="/Ai.png" alt="Logo" className={styles.modalTopBarLogo} /> ClassBridge
              </span>
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
                onKeyDown={(e) => e.key === "Enter" && handleJoinByCode()}
                maxLength={30}
              />
            </div>

            <div className={styles.modalActions}>
              <button className={styles.cancelBtn} onClick={closeJoin}>
                Hủy
              </button>
              <button
                className={styles.joinBtn}
                disabled={!classCodeInput.trim() || joining}
                onClick={handleJoinByCode}
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
          <span className={styles.logoText}>
            <img src="/Ai.png" alt="Logo" /> ClassBridge
          </span>
        </div>

        <div className={styles.topbarActions}>
          <button className={styles.bellButton} aria-label="Thông báo">🔔</button>
          <span className={styles.userLabel} title="Tài khoản đang đăng nhập">Sinh viên: {studentName || '—'}</span>
          <div className={styles.avatar} title={studentName}>{initial}</div>
          <button className={styles.logoutBtn} onClick={handleLogout}>
            Đăng xuất
          </button>
        </div>
      </header>

      <div className={styles.body}>
        <aside className={styles.sidebar}>
          <nav className={styles.navMenu}>
            {NAV_ITEMS.map(({ label, href, icon: Icon, ready }) => (
              <button
                key={href}
                type="button"
                disabled={!ready}
                title={ready ? undefined : "Sắp ra mắt"}
                onClick={() => navigate(href)}
                className={`${styles.navItem} ${pathname === href ? styles.navItemActive : ""} ${
                  ready ? "" : styles.navItemDisabled
                }`}
              >
                <Icon size={18} />
                <span>{label}</span>
              </button>
            ))}
            <div className={styles.sidebarDivider}>
              <button
                type="button"
                disabled={!SETTING_NAV_ITEM.ready}
                title="Sắp ra mắt"
                className={`${styles.navItem} ${styles.navItemDisabled}`}
              >
                <SETTING_NAV_ITEM.icon size={18} />
                <span>{SETTING_NAV_ITEM.label}</span>
              </button>
            </div>
          </nav>
        </aside>

        <main className={styles.main}>
          <h1 className={styles.greetingTitle}>Xin chào, {studentName}!</h1>
          <p className={styles.greetingSubtitle}>
            Tham gia lớp học để bắt đầu hành trình học tập cùng ClassBridge.
          </p>

          <h2 className={styles.sectionTitle}>Tham gia lớp học</h2>
          <div className={styles.joinGrid}>
            <button className={styles.joinCardPrimary} onClick={() => setJoinScreen("scanQr")}>
              <span className={styles.joinIconWrap}>
                <CameraIcon />
              </span>
              <div className={styles.joinTitle}>Quét mã QR</div>
              <div className={styles.joinSubtitle}>Dùng camera để quét mã lớp</div>
            </button>

            <button className={styles.joinCard} onClick={() => setJoinScreen("enterCode")}>
              <span className={styles.joinIconWrap}>
                <Hash />
              </span>
              <div className={styles.joinTitle}>Nhập mã lớp</div>
              <div className={styles.joinSubtitle}>Nhập mã lớp do giảng viên cung cấp</div>
            </button>
          </div>

          <div className={styles.classBox}>
            <div className={styles.classBoxHeader}>
              <h2 className={styles.sectionTitle}>Các lớp học của tôi</h2>
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
                  ? "Bạn chưa tham gia lớp nào. Hãy nhập mã lớp do giảng viên cung cấp."
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
                  <button
                    type="button"
                    className={styles.joinClassBtn}
                    onClick={() => navigate(`/room?session=${encodeURIComponent(c.liveSession!.id)}`)}
                  >
                    Vào lớp
                  </button>
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
