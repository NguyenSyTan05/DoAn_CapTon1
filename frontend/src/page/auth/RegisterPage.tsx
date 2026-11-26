"use client";

import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "@/lib/router-compat";
import { User, IdCard, Mail, Lock, Eye, EyeOff, X } from "lucide-react";
import authService from "../../services/auth.service";
import styles from "./register.module.css";

// Đăng ký trực tiếp 2 bước (không yêu cầu gửi/nhập OTP Gmail):
//   Bước 1: Thông tin sinh viên (Họ tên, MSSV 11 số, Email) -> kiểm tra trùng lặp
//   Bước 2: Đặt mật khẩu -> tạo tài khoản sinh viên & tự động đăng nhập vào /sinhvien

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const COMMON_PASSWORDS = [
  "password", "password1", "password123", "password123!", "qwerty123",
  "admin123", "welcome1", "letmein123", "iloveyou1", "abc12345",
  "12345678", "123456789", "qwerty123!", "student123!",
];

const CHECK_ERRORS: Record<string, string> = {
  email_already_registered: "Email này đã có tài khoản ClassBridge. Vui lòng đăng nhập.",
  student_code_already_registered: "Mã số sinh viên này đã được đăng ký.",
  email_check_rate_limited: "Bạn thao tác quá nhanh. Vui lòng đợi một chút rồi thử lại.",
};

type ApiErrorShape = {
  response?: {
    data?: {
      code?: string;
      message?: string;
    };
  };
};

export default function RegisterPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);

  const [fullName, setFullName] = useState("");
  const [studentCode, setStudentCode] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [agreed, setAgreed] = useState(false);

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const passwordRules = [
    { ok: password.length >= 8 && password.length <= 64, text: "Từ 8 đến 64 ký tự" },
    { ok: password.length > 0 && !/\s/.test(password), text: "Không chứa khoảng trắng" },
    { ok: /[A-Z]/.test(password), text: "Có ít nhất 1 chữ hoa" },
    { ok: /[a-z]/.test(password), text: "Có ít nhất 1 chữ thường" },
    { ok: /[0-9]/.test(password), text: "Có ít nhất 1 chữ số" },
    { ok: /[^A-Za-z0-9\s]/.test(password), text: "Có ít nhất 1 ký tự đặc biệt" },
    {
      ok: !COMMON_PASSWORDS.includes(password.toLowerCase()),
      text: "Không phải mật khẩu phổ biến",
    },
  ];
  const unmetRules = password ? passwordRules.filter((r) => !r.ok) : [];

  // Bước 1 -> kiểm tra hợp lệ & trùng Email/MSSV, chuyển thẳng sang Bước 2 đặt mật khẩu
  const handleStep1 = async () => {
    const name = fullName.trim();
    const normalizedEmail = email.trim().toLowerCase();
    if (!name) return setError("Vui lòng nhập họ và tên.");
    if (!/^\d{11}$/.test(studentCode)) return setError("Mã số sinh viên phải gồm đúng 11 chữ số.");
    if (!EMAIL_REGEX.test(normalizedEmail)) return setError("Email chưa đúng định dạng, ví dụ student@gmail.com.");

    setLoading(true);
    try {
      await authService.checkRegistrationEmail(normalizedEmail, studentCode);
      setEmail(normalizedEmail);
      setStep(2);
    } catch (unknownErr) {
      const err = unknownErr as ApiErrorShape;
      const code = err.response?.data?.code || "";
      setError(
        CHECK_ERRORS[code] ||
          err.response?.data?.message ||
          (err.response
            ? "Không thể kiểm tra thông tin đăng ký. Vui lòng thử lại."
            : "Không kết nối được máy chủ. Vui lòng kiểm tra backend."),
      );
    } finally {
      setLoading(false);
    }
  };

  // Bước 2 -> tạo tài khoản sinh viên trực tiếp, tự đăng nhập và vào /sinhvien
  const handleStep2 = async () => {
    const normalizedEmail = email.trim().toLowerCase();
    if (passwordRules.some((r) => !r.ok)) return setError("Mật khẩu chưa đáp ứng đủ yêu cầu.");
    if (password !== confirmPassword) return setError("Mật khẩu nhập lại không khớp.");
    if (!agreed) return setError("Bạn cần đồng ý với Điều khoản sử dụng và Chính sách bảo mật.");

    setLoading(true);
    try {
      await authService.registerAccount({
        fullName: fullName.trim(),
        email: normalizedEmail,
        role: "student",
        studentCode,
        password,
        confirmPassword,
      });
    } catch (unknownErr) {
      const err = unknownErr as ApiErrorShape;
      setError(err.response?.data?.message || "Không thể tạo tài khoản. Vui lòng thử lại.");
      setLoading(false);
      return;
    }

    try {
      await authService.login(normalizedEmail, password);
      navigate("/sinhvien");
    } catch {
      navigate("/login");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (loading) return;
    if (step === 1) void handleStep1();
    else if (step === 2) void handleStep2();
  };

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <button
          type="button"
          className={styles.closeBtn}
          aria-label="Đóng"
          onClick={() => navigate("/")}
        >
          <X size={15} />
        </button>

        <h1 className={styles.title}>Đăng ký</h1>
        <p className={styles.subtitle}>Tạo tài khoản sinh viên ClassBridge nhanh chóng, chỉ mất chưa đầy một phút.</p>

        <div className={styles.steps} aria-hidden="true">
          {[1, 2].map((n) => (
            <span key={n} className={`${styles.step} ${step >= n ? styles.stepActive : ""}`} />
          ))}
        </div>

        {error && <div className={styles.error} role="alert">{error}</div>}

        <form onSubmit={handleSubmit} noValidate>
          {step === 1 && (
            <>
              <p className={styles.stepLabel}>Bước 1/2 · Thông tin sinh viên</p>
              <div className={styles.formGroup}>
                <div className={styles.inputWrap}>
                  <span className={styles.inputIcon}><User size={15} /></span>
                  <input
                    type="text"
                    placeholder="Họ và tên"
                    className={styles.input}
                    maxLength={100}
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    autoComplete="name"
                  />
                </div>
              </div>
              <div className={styles.formGroup}>
                <div className={styles.inputWrap}>
                  <span className={styles.inputIcon}><IdCard size={15} /></span>
                  <input
                    type="text"
                    inputMode="numeric"
                    placeholder="Mã số sinh viên (11 chữ số)"
                    className={styles.input}
                    maxLength={11}
                    value={studentCode}
                    onChange={(e) => setStudentCode(e.target.value.replace(/\D/g, "").slice(0, 11))}
                  />
                </div>
              </div>
              <div className={styles.formGroup}>
                <div className={styles.inputWrap}>
                  <span className={styles.inputIcon}><Mail size={15} /></span>
                  <input
                    type="email"
                    placeholder="Email"
                    className={styles.input}
                    maxLength={254}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                  />
                </div>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <p className={styles.stepLabel}>Bước 2/2 · Đặt mật khẩu</p>
              <div className={styles.formGroup}>
                <div className={styles.inputWrap}>
                  <span className={styles.inputIcon}><Lock size={15} /></span>
                  <input
                    type={showPassword ? "text" : "password"}
                    placeholder="Mật khẩu"
                    className={styles.input}
                    maxLength={64}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className={styles.inputToggle}
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
                  >
                    {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
                {unmetRules.length > 0 && (
                  <ul className={styles.reqList}>
                    {unmetRules.map((r) => (
                      <li key={r.text}>• {r.text}</li>
                    ))}
                  </ul>
                )}
              </div>
              <div className={styles.formGroup}>
                <div className={styles.inputWrap}>
                  <span className={styles.inputIcon}><Lock size={15} /></span>
                  <input
                    type={showPassword ? "text" : "password"}
                    placeholder="Nhập lại mật khẩu"
                    className={styles.input}
                    maxLength={64}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    autoComplete="new-password"
                  />
                </div>
                {confirmPassword && confirmPassword !== password && (
                  <p className={styles.fieldError}>Mật khẩu nhập lại chưa khớp.</p>
                )}
              </div>
              <label className={styles.terms}>
                <input
                  type="checkbox"
                  className={styles.termsCheckbox}
                  checked={agreed}
                  onChange={(e) => setAgreed(e.target.checked)}
                />
                <span>
                  Tôi đồng ý với <a href="#" className={styles.link}>Điều khoản sử dụng</a> và{" "}
                  <a href="#" className={styles.link}>Chính sách bảo mật</a>
                </span>
              </label>
            </>
          )}

          <div className={styles.actionRow}>
            <span className={styles.signInText}>
              {step === 1 ? (
                <>Đã có tài khoản? <Link to="/login" className={styles.link}>Đăng nhập</Link></>
              ) : (
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  onClick={() => { setError(""); setStep(1); }}
                  disabled={loading}
                >
                  Quay lại
                </button>
              )}
            </span>
            <button type="submit" className={styles.submitBtn} disabled={loading}>
              {loading ? "Đang xử lý..." : step === 2 ? "ĐĂNG KÝ" : "TIẾP TỤC"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
