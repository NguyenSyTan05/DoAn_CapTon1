"use client";

import { Link } from "@/lib/router-compat";
import {
  GraduationCap,
  ArrowRight,
  Play,
  Brain,
  Languages,
  LayoutGrid,
  Sparkles,
} from "lucide-react";
import styles from "./landing.module.css";

// Trang chủ giới thiệu (giao diện lấy từ dự án /sinhvien)
export default function Landing() {
  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <Link to="/" className={styles.logoWrapper}>
          <div className={styles.logoIcon}>
            <GraduationCap size={22} color="#ffffff" />
          </div>
          <span className={styles.logoText}>ClassBridge</span>
        </Link>

        <nav className={styles.nav}>
          <a href="#tinh-nang" className={styles.navLink}>Tính năng chính</a>
          <a href="#giai-phap" className={styles.navLink}>Giải pháp EMI</a>
          <a href="#hieu-qua" className={styles.navLink}>Hiệu quả</a>
        </nav>

        <div className={styles.authGroup}>
          <Link to="/login" className={styles.loginBtn}>Đăng nhập</Link>
          <Link to="/register" className={styles.signupBtn}>Đăng ký</Link>
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
          <Link to="/login" className={styles.actionLink}>
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

      <footer className={styles.footer}>
        <div className={styles.footerContainer}>
          <div className={styles.footerContent}>
            <div className={styles.footerBrand}>
              <img src="/logotachnen.png" className={styles.footerLogo} alt="Logo" />
              <p>ClassBridge - AI</p>
            </div>
            <div className={styles.footerColumn}>
              <h3>Điều hướng</h3>
              <ul>
                <li><Link to="/">Trang chủ</Link></li>
                <li><a href="#">Giới thiệu</a></li>
              </ul>
            </div>
            <div className={styles.footerColumn}>
              <h3>Hỗ trợ</h3>
              <ul>
                <li><a href="#">Chính sách Bảo mật</a></li>
                <li><a href="#">Điều khoản Dịch vụ</a></li>
                <li><a href="#">Trung tâm trợ giúp</a></li>
              </ul>
            </div>
            <div className={styles.footerColumn}>
              <h3>Liên hệ</h3>
              <ul>
                <li>Đà Nẵng</li>
                <li>classbridge38@gmail.com</li>
              </ul>
            </div>
          </div>
          <div className={styles.footerCopyright}>
            &copy; 2026 ClassBridge - AI. Trợ giảng hỗ trợ công nghệ dành cho
            giảng viên nước ngoài tại DTU.
          </div>
        </div>
      </footer>
    </div>
  );
}
