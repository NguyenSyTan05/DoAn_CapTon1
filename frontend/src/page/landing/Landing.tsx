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

          <button type="button" className={styles.secondaryBtn}>
            <span className={styles.playIconWrapper}>
              <Play size={10} fill="currentColor" />
            </span>
            Tìm hiểu thêm
          </button>
        </div>
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
