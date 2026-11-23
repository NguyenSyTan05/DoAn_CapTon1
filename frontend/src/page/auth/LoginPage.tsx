"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "@/lib/router-compat";
import authService from "../../services/auth.service";
import styles from "./login.module.css";

// Giao diện lấy từ /sinhvien; logic đăng nhập dùng API Flask (/auth/login).
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const ROLE_HOME: Record<string, string> = {
  sinh_vien: "/sinhvien",
  giang_vien: "/giangvien",
  admin: "/admin",
};

export default function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Bị đẩy về /login?expired=1 khi token hết hạn
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("expired")) {
      setError("Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.");
    }
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!EMAIL_REGEX.test(email.trim())) {
      setError("Email chưa đúng định dạng, ví dụ student@gmail.com.");
      return;
    }
    if (!password) {
      setError("Vui lòng nhập mật khẩu.");
      return;
    }

    setLoading(true);
    try {
      const data = await authService.login(email.trim().toLowerCase(), password);
      const target = ROLE_HOME[data.user?.role];
      if (target) navigate(target);
      else setError("Tài khoản không hợp lệ.");
    } catch (err: any) {
      const status = err.response?.status;
      const code = err.response?.data?.code;
      if (code === "email_not_found") setError("Email này chưa được đăng ký.");
      else if (code === "account_disabled") setError("Tài khoản này đã bị vô hiệu hóa.");
      else if (code === "password_incorrect") setError("Mật khẩu không chính xác.");
      else if (code === "invalid_email") setError("Email chưa đúng định dạng.");
      else if (code === "invalid_password") setError("Mật khẩu phải có từ 1 đến 64 ký tự.");
      else if (status === 429) setError("Bạn đã thử đăng nhập quá nhiều lần. Vui lòng thử lại sau.");
      else if (status === 503) setError("Đăng nhập tạm thời không khả dụng. Vui lòng thử lại sau.");
      else if (!err.response) setError("Không kết nối được máy chủ. Vui lòng kiểm tra backend.");
      else setError("Đăng nhập thất bại. Vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <main className={styles.main}>
        <div className={styles.card}>
          <div className={styles.title}>
            <h1>Chào mừng trở lại</h1>
            <p>Truy cập vào ClassBridge – AI của bạn</p>
          </div>

          {error && (
            <div className={styles["error-box"]} role="alert">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate>
            <div className={styles["form-login"]}>
              <label className={styles["form-label"]} htmlFor="login-email">
                Địa chỉ Email
              </label>
              <div className={styles["input-wrapper"]}>
                <img src="/mail.png" alt="" style={{ width: 20, height: 20 }} />
                <input
                  id="login-email"
                  type="email"
                  maxLength={254}
                  placeholder="Vui lòng nhập email của bạn"
                  className={styles["form-input"]}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  required
                />
              </div>
            </div>

            <div className={styles["form-login"]}>
              <label className={styles["form-label"]} htmlFor="login-password">
                Mật khẩu
              </label>
              <div className={styles["input-wrapper"]}>
                <img src="/lock.png" alt="" style={{ width: 20, height: 20 }} />
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  maxLength={64}
                  placeholder="Vui lòng nhập mật khẩu"
                  className={styles["form-input"]}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  className={styles["eye-btn"]}
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                >
                  <img src="/eye.png" alt="" />
                </button>
              </div>
            </div>

            <div className={styles["form-options"]}>
              <span />
              <Link to="/forgot-password" className={styles["forgot-pass"]}>
                Quên mật khẩu?
              </Link>
            </div>

            <button type="submit" className={styles["btn-submit"]} disabled={loading}>
              {loading ? "Đang xử lý..." : "Đăng nhập ngay"}
            </button>
          </form>

          <p className={styles["register-prompt"]}>
            Bạn chưa có tài khoản? <Link to="/register">Đăng ký ngay →</Link>
          </p>
          <Link to="/" className={styles["back-home"]}>
            ← Về trang chủ
          </Link>
        </div>
      </main>
    </div>
  );
}
