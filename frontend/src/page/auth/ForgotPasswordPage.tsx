"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "@/lib/router-compat";
import { Eye, EyeOff, Lock, Mail, X } from "lucide-react";
import authService from "../../services/auth.service";
import styles from "./register.module.css";

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const COMMON_PASSWORDS = [
  "password",
  "password1",
  "password123",
  "password123!",
  "qwerty123",
  "admin123",
  "welcome1",
  "letmein123",
  "iloveyou1",
  "abc12345",
  "12345678",
  "123456789",
  "qwerty123!",
  "student123!",
];

type ApiErrorShape = {
  response?: {
    status?: number;
    data?: {
      code?: string;
      message?: string;
    };
  };
};

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);

  const [email, setEmail] = useState("");
  const [verifiedEmail, setVerifiedEmail] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [choices, setChoices] = useState<number[]>([]);
  const [devCode, setDevCode] = useState<number | null>(null);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (step !== 2 || expiresAt === null) return;
    const tick = () =>
      setSecondsLeft(Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000)));
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [step, expiresAt]);

  const passwordRules = [
    { ok: password.length >= 8 && password.length <= 64, text: "Từ 8 đến 64 ký tự" },
    { ok: password.length > 0 && !/\s/.test(password), text: "Không chứa khoảng trắng" },
    { ok: /[A-Z]/.test(password), text: "Có ít nhất 1 chữ hoa" },
    { ok: /[a-z]/.test(password), text: "Có ít nhất 1 chữ thường" },
    { ok: /[0-9]/.test(password), text: "Có ít nhất 1 chữ số" },
    { ok: /[^A-Za-z0-9\s]/.test(password), text: "Có ít nhất 1 ký tự đặc biệt" },
    {
      ok: password.length > 0 && !COMMON_PASSWORDS.includes(password.toLowerCase()),
      text: "Không phải mật khẩu phổ biến",
    },
  ];
  const unmetRules = password ? passwordRules.filter((r) => !r.ok) : [];

  const applyChallenge = (c: { challengeId?: string; expiresIn: number; choices: number[]; devCode?: number }) => {
    if (c.challengeId) setChallengeId(c.challengeId);
    setChoices(c.choices);
    setDevCode(typeof c.devCode === "number" ? c.devCode : null);
    setExpiresAt(Date.now() + c.expiresIn * 1000);
  };

  // Bước 1 -> gửi email chứa con số khôi phục mật khẩu
  const handleStep1 = async () => {
    const normalizedEmail = email.trim().toLowerCase();
    if (!EMAIL_REGEX.test(normalizedEmail)) {
      setError("Địa chỉ email chưa đúng định dạng, ví dụ student@gmail.com.");
      return;
    }

    setLoading(true);
    try {
      const challenge = await authService.sendForgotPasswordVerification(normalizedEmail);
      setVerifiedEmail(normalizedEmail);
      setResetToken("");
      applyChallenge(challenge);
      setStep(2);
    } catch (unknownErr) {
      const err = unknownErr as ApiErrorShape;
      setError(
        err.response?.data?.message ||
          (err.response
            ? "Máy chủ không gửi được email khôi phục. Vui lòng kiểm tra cấu hình SMTP."
            : "Không kết nối được máy chủ. Vui lòng kiểm tra backend."),
      );
    } finally {
      setLoading(false);
    }
  };

  // Bước 2 -> chọn đúng con số từ email để nhận resetToken 1 lần
  const handleChoice = async (selected: number) => {
    if (loading) return;
    if (secondsLeft <= 0) {
      setError("Mã xác minh đã hết hạn. Vui lòng bấm Gửi lại.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const result = await authService.verifyForgotPasswordCode(challengeId, selected);
      if (result.verified && result.resetToken) {
        setResetToken(result.resetToken);
        setStep(3);
      } else if (Array.isArray(result.choices)) {
        applyChallenge({ expiresIn: result.expiresIn, choices: result.choices, devCode: result.devCode });
        setError(
          result.message || "Con số vừa chọn chưa đúng. Một số mới đã được gửi đến email của bạn.",
        );
      } else {
        setError("Không xác minh được mã khôi phục. Vui lòng thử lại.");
      }
    } catch (unknownErr) {
      const err = unknownErr as ApiErrorShape;
      const code = err.response?.data?.code;
      setError(err.response?.data?.message || "Không xác minh được email. Vui lòng thử lại.");
      if (code === "too_many_wrong_choices" || code === "challenge_expired") {
        setChallengeId("");
        setResetToken("");
        setStep(1);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    if (!verifiedEmail) return;
    setLoading(true);
    setError("");
    try {
      const challenge = await authService.sendForgotPasswordVerification(verifiedEmail);
      setResetToken("");
      applyChallenge(challenge);
    } catch (unknownErr) {
      const err = unknownErr as ApiErrorShape;
      setError(err.response?.data?.message || "Chưa thể gửi lại mã xác thực. Vui lòng đợi ít giây.");
    } finally {
      setLoading(false);
    }
  };

  // Bước 3 -> đặt mật khẩu mới bằng resetToken một lần
  const handleStep3 = async () => {
    if (passwordRules.some((r) => !r.ok)) {
      setError("Mật khẩu mới chưa đáp ứng đủ các yêu cầu bảo mật.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Mật khẩu xác nhận không khớp.");
      return;
    }

    setLoading(true);
    try {
      await authService.resetForgotPassword({
        email: verifiedEmail,
        challengeId,
        resetToken,
        password,
        confirmPassword,
      });
      navigate("/login?reset=1", { replace: true });
    } catch (unknownErr) {
      const err = unknownErr as ApiErrorShape;
      const code = err.response?.data?.code;
      setError(err.response?.data?.message || "Không thể đặt lại mật khẩu. Vui lòng thử lại.");
      if (code === "invalid_reset_session") {
        setChallengeId("");
        setResetToken("");
        setStep(1);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (loading) return;
    if (step === 1) void handleStep1();
    else if (step === 3) void handleStep3();
  };

  const mmss = `${String(Math.floor(secondsLeft / 60)).padStart(2, "0")}:${String(
    secondsLeft % 60,
  ).padStart(2, "0")}`;

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <button
          type="button"
          className={styles.closeBtn}
          aria-label="Đóng"
          onClick={() => navigate("/login")}
        >
          <X size={15} />
        </button>

        <h1 className={styles.title}>Quên mật khẩu</h1>
        <p className={styles.subtitle}>
          Khôi phục mật khẩu tài khoản Sinh viên, Giảng viên hoặc Quản trị viên qua xác thực email.
        </p>

        <div className={styles.steps} aria-hidden="true">
          {[1, 2, 3].map((n) => (
            <span key={n} className={`${styles.step} ${step >= n ? styles.stepActive : ""}`} />
          ))}
        </div>

        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} noValidate>
          {step === 1 && (
            <>
              <p className={styles.stepLabel}>Bước 1/3 · Nhập email tài khoản</p>
              <div className={styles.formGroup}>
                <div className={styles.inputWrap}>
                  <span className={styles.inputIcon}>
                    <Mail size={15} />
                  </span>
                  <input
                    type="email"
                    placeholder="Nhập địa chỉ email đã đăng ký"
                    className={styles.input}
                    maxLength={254}
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      setChallengeId("");
                      setResetToken("");
                    }}
                    autoComplete="email"
                  />
                </div>
              </div>
              <p className={styles.hint}>
                Hệ thống sẽ gửi một con số xác thực về hộp thư của bạn để xác nhận quyền sở hữu tài khoản.
              </p>
            </>
          )}

          {step === 2 && (
            <>
              <p className={styles.stepLabel}>Bước 2/3 · Xác thực email</p>
              <p className={styles.hint}>
                Chúng tôi đã gửi một con số đến <strong>{verifiedEmail}</strong>. Hãy chọn đúng con số có trong email:
              </p>
              {devCode !== null && (
                <p
                  style={{
                    margin: "8px 0 12px",
                    padding: "8px 12px",
                    borderRadius: 8,
                    background: "#eef4ff",
                    color: "#1d4ed8",
                    fontSize: 13,
                    textAlign: "center",
                  }}
                >
                  Chế độ test cục bộ (chưa điền SMTP): Con số cần chọn là <strong>{devCode}</strong>
                </p>
              )}
              <p
                className={`${styles.timer} ${secondsLeft === 0 ? styles.timerExpired : ""}`}
                role="timer"
              >
                {secondsLeft === 0 ? "Mã đã hết hạn" : `Thời gian còn lại: ${mmss}`}
              </p>
              <div className={styles.choices}>
                {choices.map((c) => (
                  <button
                    key={c}
                    type="button"
                    className={styles.choiceBtn}
                    disabled={loading || secondsLeft === 0}
                    onClick={() => void handleChoice(c)}
                  >
                    {c}
                  </button>
                ))}
              </div>
              <p className={styles.hint}>
                Chưa nhận được email?{" "}
                <button
                  type="button"
                  className={styles.linkBtn}
                  onClick={() => void handleResend()}
                  disabled={loading}
                >
                  Gửi lại mã
                </button>
              </p>
            </>
          )}

          {step === 3 && (
            <>
              <p className={styles.stepLabel}>Bước 3/3 · Đặt mật khẩu mới</p>
              <div className={styles.formGroup}>
                <div className={styles.inputWrap}>
                  <span className={styles.inputIcon}>
                    <Lock size={15} />
                  </span>
                  <input
                    type={showPassword ? "text" : "password"}
                    placeholder="Mật khẩu mới"
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
                  <span className={styles.inputIcon}>
                    <Lock size={15} />
                  </span>
                  <input
                    type={showPassword ? "text" : "password"}
                    placeholder="Nhập lại mật khẩu mới"
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
            </>
          )}

          <div className={styles.actionRow}>
            <span className={styles.signInText}>
              {step === 1 ? (
                <>
                  Nhớ mật khẩu?{" "}
                  <Link to="/login" className={styles.link}>
                    Đăng nhập
                  </Link>
                </>
              ) : (
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  onClick={() => {
                    setError("");
                    setStep(step - 1);
                  }}
                  disabled={loading}
                >
                  Quay lại
                </button>
              )}
            </span>
            {step !== 2 && (
              <button type="submit" className={styles.submitBtn} disabled={loading}>
                {loading ? "Đang xử lý..." : step === 3 ? "LƯU MẬT KHẨU MỚI" : "GỬI MÃ XÁC THỰC"}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
