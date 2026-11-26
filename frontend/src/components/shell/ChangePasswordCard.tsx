"use client";

import React, { useState } from "react";
import { CheckCircle2, Eye, EyeOff, KeyRound, Lock } from "lucide-react";
import authService from "../../services/auth.service";

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

type ChangePasswordCardProps = {
  maxWidth?: number | string;
  title?: string;
  subtitle?: string;
};

export default function ChangePasswordCard({
  maxWidth = 620,
  title = "Đổi mật khẩu tài khoản",
  subtitle = "Sử dụng mật khẩu mạnh từ 8–64 ký tự gồm chữ hoa, chữ thường, chữ số và ký tự đặc biệt.",
}: ChangePasswordCardProps) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  const passwordRules = [
    { ok: newPassword.length >= 8 && newPassword.length <= 64, text: "Độ dài từ 8 đến 64 ký tự" },
    { ok: newPassword.length > 0 && !/\s/.test(newPassword), text: "Không chứa khoảng trắng" },
    { ok: /[A-Z]/.test(newPassword), text: "Có ít nhất 1 chữ cái in hoa" },
    { ok: /[a-z]/.test(newPassword), text: "Có ít nhất 1 chữ cái thường" },
    { ok: /[0-9]/.test(newPassword), text: "Có ít nhất 1 chữ số" },
    { ok: /[^A-Za-z0-9\s]/.test(newPassword), text: "Có ít nhất 1 ký tự đặc biệt" },
    {
      ok: newPassword.length > 0 && !COMMON_PASSWORDS.includes(newPassword.toLowerCase()),
      text: "Không trùng mật khẩu phổ biến",
    },
  ];

  const unmetRules = newPassword ? passwordRules.filter((r) => !r.ok) : [];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSuccessMsg("");
    setErrorMsg("");

    if (!currentPassword) {
      setErrorMsg("Vui lòng nhập mật khẩu hiện tại.");
      return;
    }
    if (passwordRules.some((r) => !r.ok)) {
      setErrorMsg("Mật khẩu mới chưa đáp ứng đầy đủ các tiêu chuẩn bảo mật.");
      return;
    }
    if (newPassword === currentPassword) {
      setErrorMsg("Mật khẩu mới phải khác mật khẩu hiện tại.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setErrorMsg("Mật khẩu xác nhận không khớp.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await authService.changePassword(currentPassword, newPassword, confirmPassword);
      setSuccessMsg(res?.message || "Đổi mật khẩu thành công!");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (unknownErr) {
      const err = unknownErr as ApiErrorShape;
      setErrorMsg(
        err.response?.data?.message ||
          (err.response
            ? "Không thể đổi mật khẩu. Vui lòng kiểm tra lại thông tin."
            : "Không kết nối được máy chủ. Vui lòng kiểm tra backend."),
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      style={{
        maxWidth,
        background: "#ffffff",
        border: "1px solid #e2e8f0",
        borderRadius: 14,
        padding: 24,
        display: "flex",
        flexDirection: "column",
        gap: 14,
      }}
    >
      <div>
        <h2
          style={{
            margin: "0 0 4px",
            fontSize: 18,
            fontWeight: 700,
            color: "#0f172a",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <KeyRound size={18} color="#2563eb" />
          {title}
        </h2>
        <p style={{ margin: 0, fontSize: 13, color: "#64748b" }}>{subtitle}</p>
      </div>

      {successMsg && (
        <div
          role="status"
          style={{
            padding: "10px 12px",
            borderRadius: 8,
            background: "#ecfdf5",
            border: "1px solid #a7f3d0",
            color: "#047857",
            fontSize: 13,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <CheckCircle2 size={16} />
          <span>{successMsg}</span>
        </div>
      )}

      {errorMsg && (
        <div
          role="alert"
          style={{
            padding: "10px 12px",
            borderRadius: 8,
            background: "#fef2f2",
            border: "1px solid #fecaca",
            color: "#b91c1c",
            fontSize: 13,
          }}
        >
          {errorMsg}
        </div>
      )}

      <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600, color: "#1e293b" }}>
        Mật khẩu hiện tại
        <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
          <Lock size={15} color="#64748b" style={{ position: "absolute", left: 12, pointerEvents: "none" }} />
          <input
            type={showCurrent ? "text" : "password"}
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            maxLength={64}
            placeholder="Nhập mật khẩu đang sử dụng"
            autoComplete="current-password"
            style={{
              width: "100%",
              padding: "9px 38px 9px 36px",
              borderRadius: 8,
              border: "1px solid #cbd5e1",
              fontSize: 13.5,
            }}
          />
          <button
            type="button"
            onClick={() => setShowCurrent((v) => !v)}
            aria-label={showCurrent ? "Ẩn mật khẩu hiện tại" : "Hiện mật khẩu hiện tại"}
            style={{
              position: "absolute",
              right: 8,
              background: "transparent",
              border: "none",
              color: "#64748b",
              cursor: "pointer",
              padding: 4,
              display: "inline-flex",
            }}
          >
            {showCurrent ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600, color: "#1e293b" }}>
        Mật khẩu mới
        <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
          <Lock size={15} color="#64748b" style={{ position: "absolute", left: 12, pointerEvents: "none" }} />
          <input
            type={showNew ? "text" : "password"}
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            maxLength={64}
            placeholder="Nhập mật khẩu mới"
            autoComplete="new-password"
            style={{
              width: "100%",
              padding: "9px 38px 9px 36px",
              borderRadius: 8,
              border: "1px solid #cbd5e1",
              fontSize: 13.5,
            }}
          />
          <button
            type="button"
            onClick={() => setShowNew((v) => !v)}
            aria-label={showNew ? "Ẩn mật khẩu mới" : "Hiện mật khẩu mới"}
            style={{
              position: "absolute",
              right: 8,
              background: "transparent",
              border: "none",
              color: "#64748b",
              cursor: "pointer",
              padding: 4,
              display: "inline-flex",
            }}
          >
            {showNew ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
        {unmetRules.length > 0 && (
          <ul style={{ margin: "4px 0 0", paddingLeft: 18, fontSize: 12, fontWeight: 400, color: "#b45309" }}>
            {unmetRules.map((rule) => (
              <li key={rule.text}>{rule.text}</li>
            ))}
          </ul>
        )}
      </label>

      <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, fontWeight: 600, color: "#1e293b" }}>
        Xác nhận mật khẩu mới
        <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
          <Lock size={15} color="#64748b" style={{ position: "absolute", left: 12, pointerEvents: "none" }} />
          <input
            type={showNew ? "text" : "password"}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            maxLength={64}
            placeholder="Nhập lại mật khẩu mới"
            autoComplete="new-password"
            style={{
              width: "100%",
              padding: "9px 12px 9px 36px",
              borderRadius: 8,
              border: "1px solid #cbd5e1",
              fontSize: 13.5,
            }}
          />
        </div>
        {confirmPassword.length > 0 && confirmPassword !== newPassword && (
          <span style={{ fontSize: 12, fontWeight: 500, color: "#dc2626" }}>Mật khẩu xác nhận chưa khớp.</span>
        )}
      </label>

      <button
        type="submit"
        disabled={submitting}
        style={{
          alignSelf: "flex-start",
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          background: "#2563eb",
          color: "#ffffff",
          border: "none",
          borderRadius: 10,
          padding: "10px 18px",
          fontWeight: 600,
          fontSize: 13.5,
          cursor: submitting ? "not-allowed" : "pointer",
          opacity: submitting ? 0.7 : 1,
        }}
      >
        <KeyRound size={16} />
        {submitting ? "Đang cập nhật..." : "Cập nhật mật khẩu"}
      </button>
    </form>
  );
}
