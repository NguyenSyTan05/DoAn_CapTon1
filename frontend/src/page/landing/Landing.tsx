"use client";

import Image from "next/image";
import { Link } from "@/lib/router-compat";
import { useStoredSession } from "@/lib/session";
import api from "../../services/api";
import authService from "../../services/auth.service";
import {
  ArrowRight,
  Play,
  Brain,
  Languages,
  LayoutGrid,
  Sparkles,
} from "lucide-react";
import Footer from "@/components/shell/footer";
import styles from "./landing.module.css";

// Trang chủ giới thiệu (giao diện lấy từ dự án /sinhvien)
export default function Landing() {
  // Đã đăng nhập (token còn hạn) -> hiện tài khoản và đưa thẳng vào trang theo vai trò
  const session = useStoredSession();
  const startHref = session ? session.home : "/login";

  const handleLogout = async () => {
    try {
      await api.post("/auth/logout"); // ghi audit log, lỗi cũng bỏ qua (giống trang sinh viên)
    } catch {
      /* ignore */
    }
    authService.logout();
    // Báo cho useStoredSession cập nhật ngay trong tab hiện tại
    window.dispatchEvent(new Event("storage"));
  };

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <Link to="/" className={styles.logoWrapper}>
          <span className={styles.logoIcon}>
            <Image
              src="/classbridge-logo-transparent.png"
              alt=""
              width={42}
              height={42}
              preload
            />
          </span>
          <span className={styles.logoText}>ClassBridge</span>
        </Link>

        <nav className={styles.nav}>
          <a href="#tinh-nang" className={styles.navLink}>Tính năng chính</a>
          <a href="#giai-phap" className={styles.navLink}>Giải pháp EMI</a>
          <a href="#hieu-qua" className={styles.navLink}>Hiệu quả</a>
        </nav>

        <div className={styles.authGroup}>
          {session ? (
            <>
              <button type="button" onClick={handleLogout} className={styles.loginBtn}>
                Đăng xuất
              </button>
              <Link to={session.home} className={styles.signupBtn}>
                {session.user.full_name || session.user.email || "Tài khoản"} · Vào hệ thống
              </Link>
            </>
          ) : (
            <>
              <Link to="/login" className={styles.loginBtn}>Đăng nhập</Link>
              <Link to="/register" className={styles.signupBtn}>Đăng ký</Link>
            </>
          )}
        </div>
      </header>

      <main className={styles.main}>
        <div className={styles.badge}>
          <Sparkles size={14} />
          Trợ lý AI chuyên dụng cho lớp học quốc tế DTU
        </div>

        <h1 className={styles.title}>
          Phá vỡ rào cản ngôn ngữ trong <br />
          <span className={styles.highlightText}>Lớp học Song ngữ EMI</span>
        </h1>

        <p className={styles.subtitle}>
          *Tích hợp công nghệ Speech-to-Text, dịch thuật thời gian thực và nhóm
          câu hỏi thông minh giúp kết nối hoàn hảo giữa giảng viên nước ngoài và
          sinh viên.
        </p>

        <div className={styles.actionButtons}>
          <Link to={startHref} className={styles.actionLink}>
            <button type="button" className={styles.primaryBtn}>
              Vào phòng học ngay
              <ArrowRight size={16} />
            </button>
          </Link>

          <button
            type="button"
            className={styles.secondaryBtn}
            onClick={() =>
              document.getElementById("tinh-nang")?.scrollIntoView({ behavior: "smooth" })
            }
          >
            <span className={styles.playIconWrapper}>
              <Play size={10} fill="currentColor" />
            </span>
            Tìm hiểu thêm
          </button>
        </div>

        <section
          id="tinh-nang"
          style={{
            width: "100%",
            maxWidth: 1040,
            margin: "56px auto 0",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            gap: 18,
            textAlign: "left",
          }}
        >
          <div style={{ background: "rgba(15, 23, 42, 0.72)", border: "1px solid rgba(148,163,184,0.2)", borderRadius: 16, padding: 22 }}>
            <Languages size={24} color="#38bdf8" />
            <h3 style={{ margin: "12px 0 8px", fontSize: 18, color: "#f8fafc" }}>Phụ đề Song ngữ Thời gian thực</h3>
            <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "#cbd5e1" }}>
              Nhận dạng giọng nói giảng viên (Faster-Whisper) và dịch tức thì Anh ↔ Việt qua NLLB-200 với luồng progressive độ trễ thấp.
            </p>
          </div>
          <div id="giai-phap" style={{ background: "rgba(15, 23, 42, 0.72)", border: "1px solid rgba(148,163,184,0.2)", borderRadius: 16, padding: 22 }}>
            <Brain size={24} color="#a78bfa" />
            <h3 style={{ margin: "12px 0 8px", fontSize: 18, color: "#f8fafc" }}>Hỏi đáp Ẩn danh & Gom cụm AI</h3>
            <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "#cbd5e1" }}>
              Sinh viên tự tin đặt câu hỏi bằng tiếng Việt hoặc tiếng Anh; mô hình ngữ nghĩa MiniLM tự động gom các câu trùng ý cho giảng viên.
            </p>
          </div>
          <div id="hieu-qua" style={{ background: "rgba(15, 23, 42, 0.72)", border: "1px solid rgba(148,163,184,0.2)", borderRadius: 16, padding: 22 }}>
            <LayoutGrid size={24} color="#34d399" />
            <h3 style={{ margin: "12px 0 8px", fontSize: 18, color: "#f8fafc" }}>Tóm tắt Bài giảng & Heatmap</h3>
            <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "#cbd5e1" }}>
              Tổng hợp cấu trúc bài học, từ vựng học thuật và bản đồ nhiệt mức độ thắc mắc theo từng trang slide ngay sau buổi giảng.
            </p>
          </div>
        </section>
      </main>

      <aside aria-label="Quick Tools" className={styles.sidebar}>
        <div className={`${styles.sidebarIcon} ${styles.sidebarIconBrain}`}>
          <Brain size={18} />
        </div>
        <div className={styles.sidebarIcon}>
          <Languages size={18} />
        </div>
        <div className={styles.sidebarIcon}>
          <LayoutGrid size={18} />
        </div>
        <div className={styles.sidebarIconActive}>
          <span>AI</span>
        </div>
      </aside>

      <Footer language="vi" />
    </div>
  );
}
