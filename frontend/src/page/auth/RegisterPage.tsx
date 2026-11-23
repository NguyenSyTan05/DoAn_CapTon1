"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "@/lib/router-compat";
import { User, IdCard, Mail, Lock, Eye, EyeOff, X } from "lucide-react";
import authService from "../../services/auth.service";
import styles from "./register.module.css";

// Giao diện lấy từ /sinhvien; logic đăng ký dùng API Flask:
//   bước 1: thông tin  ->  bước 2: xác thực email (chọn đúng số)  ->  bước 3: mật khẩu.
// Vai trò luôn là sinh viên; đăng ký xong tự đăng nhập và vào trang chủ sinh viên.

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const COMMON_PASSWORDS = [
  "password", "password1", "password123", "password123!", "qwerty123",
  "admin123", "welcome1", "letmein123", "iloveyou1", "abc12345",
  "12345678", "123456789", "qwerty123!", "student123!",
];

const SEND_ERRORS: Record<string, string> = {
  email_already_registered: "Email này đã có tài khoản ClassBridge. Vui lòng đăng nhập.",
  email_not_found: "Không tìm thấy email này hoặc email không nhận được thư. Vui lòng kiểm tra lại.",
  email_could_not_verify: "Chưa xác minh được email này. Vui lòng dùng email khác.",
  email_validation_unavailable: "Dịch vụ kiểm tra email đang tạm thời không khả dụng. Vui lòng thử lại sau.",
  email_validation_configuration_error: "Cấu hình API kiểm tra email chưa đúng. Vui lòng báo quản trị viên.",
  email_validation_quota_exceeded: "Dịch vụ kiểm tra email đã hết lượt sử dụng. Vui lòng báo quản trị viên.",
  email_validation_rate_limited: "Bạn thao tác quá nhanh. Vui lòng đợi một chút rồi thử lại.",
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

  const [challengeId, setChallengeId] = useState("");
  const [verifiedEmail, setVerifiedEmail] = useState("");
  const [choices, setChoices] = useState<number[]>([]);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const [secondsLeft, setSecondsLeft] = useState(0);

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

  const applyChallenge = (c: { challengeId?: string; expiresIn: number; choices: number[] }) => {
    if (c.challengeId) setChallengeId(c.challengeId);
    setChoices(c.choices);
    setExpiresAt(Date.now() + c.expiresIn * 1000);
  };

  // Bước 1 -> gửi email chứa số xác thực
  const handleStep1 = async () => {
    const name = fullName.trim();
    const normalizedEmail = email.trim().toLowerCase();
    if (!name) return setError("Vui lòng nhập họ và tên.");
    if (!/^\d{11}$/.test(studentCode)) return setError("Mã số sinh viên phải gồm đúng 11 chữ số.");
    if (!EMAIL_REGEX.test(normalizedEmail)) return setError("Email chưa đúng định dạng, ví dụ student@gmail.com.");

    // Đã xác thực cho đúng email này rồi thì khỏi gửi lại
    if (challengeId && verifiedEmail === normalizedEmail) {
      setStep(2);
      return;
    }

    setLoading(true);
    try {
      const challenge = await authService.sendRegistrationVerification(normalizedEmail);
      setVerifiedEmail(normalizedEmail);
      applyChallenge(challenge);
      setStep(2);
    } catch (err: any) {
      const code = err.response?.data?.code;
      setError(
        SEND_ERRORS[code] ||
          err.response?.data?.message ||
          (err.response
            ? "Máy chủ không gửi được email xác minh. Vui lòng kiểm tra cấu hình SMTP."
            : "Không kết nối được máy chủ. Vui lòng kiểm tra backend."),
      );
    } finally {
      setLoading(false);
    }
  };

  // Bước 2 -> chọn số
  const handleChoice = async (selected: number) => {
    if (loading) return;
    if (secondsLeft <= 0) return setError("Mã xác minh đã hết hạn. Vui lòng gửi lại email.");
    setLoading(true);
    setError("");
    try {
      const result = await authService.verifyRegistrationCode(challengeId, selected);
      if (result.verified) {
        setStep(3);
      } else if (Array.isArray(result.choices)) {
        applyChallenge({ expiresIn: result.expiresIn, choices: result.choices });
        setError("Số vừa chọn chưa đúng. Đã gửi số mới đến email, hãy chọn lại.");
      } else {
        setError("Không xác minh được email. Vui lòng thử lại.");
      }
    } catch (err: any) {
      setError(err.response?.data?.message || "Không xác minh được email. Vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    setLoading(true);
    setError("");
    try {
      applyChallenge(await authService.sendRegistrationVerification(verifiedEmail));
    } catch (err: any) {
      setError(err.response?.data?.message || "Không gửi lại được email xác minh.");
    } finally {
      setLoading(false);
    }
  };

  // Bước 3 -> tạo tài khoản sinh viên, tự đăng nhập, vào trang chủ sinh viên
  const handleStep3 = async () => {
    if (passwordRules.some((r) => !r.ok)) return setError("Mật khẩu chưa đáp ứng đủ yêu cầu.");
    if (password !== confirmPassword) return setError("Mật khẩu nhập lại không khớp.");
    if (!agreed) return setError("Bạn cần đồng ý với Điều khoản sử dụng và Chính sách bảo mật.");

    setLoading(true);
    try {
      await authService.registerAccount({
        fullName: fullName.trim(),
        email: verifiedEmail,
        role: "student",
        studentCode,
        password,
        confirmPassword,
        challengeId,
      });
    } catch (err: any) {
      setError(err.response?.data?.message || "Không thể tạo tài khoản. Vui lòng thử lại.");
      setLoading(false);
      return;
    }

    try {
      await authService.login(verifiedEmail, password);
      navigate("/sinhvien");
    } catch {
      // Tạo tài khoản được nhưng tự đăng nhập lỗi -> cho người dùng đăng nhập tay
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
    else if (step === 3) void handleStep3();
  };

  const mmss = `${String(Math.floor(secondsLeft / 60)).padStart(2, "0")}:${String(secondsLeft % 60).padStart(2, "0")}`;

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
        <p className={styles.subtitle}>Tạo tài khoản sinh viên ClassBridge. Miễn phí và chỉ mất một phút.</p>

        <div className={styles.steps} aria-hidden="true">
          {[1, 2, 3].map((n) => (
            <span key={n} className={`${styles.step} ${step >= n ? styles.stepActive : ""}`} />
          ))}
        </div>

        {error && <div className={styles.error} role="alert">{error}</div>}

        <form onSubmit={handleSubmit} noValidate>
          {step === 1 && (
            <>
              <p className={styles.stepLabel}>Bước 1/3 · Thông tin sinh viên</p>
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
                    onChange={(e) => {
                      setEmail(e.target.value);
                      setChallengeId("");
                      setVerifiedEmail("");
                    }}
                    autoComplete="email"
                  />
                </div>
              </div>
            </>
          )}

          {step === 2 && (
            <>
              <p className={styles.stepLabel}>Bước 2/3 · Xác thực email</p>
              <p className={styles.hint}>
                Chúng tôi đã gửi một con số đến <strong>{verifiedEmail}</strong>. Hãy chọn đúng số có trong email:
              </p>
              <p className={`${styles.timer} ${secondsLeft === 0 ? styles.timerExpired : ""}`} role="timer">
                {secondsLeft === 0 ? "Mã đã hết hạn" : `Thời gian còn lại: ${mmss}`}
              </p>
              <div className={styles.choices}>
                {choices.map((c) => (
                  <button
                    key={c}
                    type="button"
                    className={styles.choiceBtn}
                    disabled={loading || secondsLeft === 0}
                    onClick={() => handleChoice(c)}
                  >
                    {c}
                  </button>
                ))}
              </div>
              <p className={styles.hint}>
                Không nhận được email?{" "}
                <button type="button" className={styles.linkBtn} onClick={handleResend} disabled={loading}>
                  Gửi lại
                </button>
              </p>
            </>
          )}

          {step === 3 && (
            <>
              <p className={styles.stepLabel}>Bước 3/3 · Đặt mật khẩu</p>
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
                  onClick={() => { setError(""); setStep(step - 1); }}
                  disabled={loading}
                >
                  Quay lại
                </button>
              )}
            </span>
            {step !== 2 && (
              <button type="submit" className={styles.submitBtn} disabled={loading}>
                {loading ? "Đang xử lý..." : step === 3 ? "ĐĂNG KÝ" : "TIẾP TỤC"}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
