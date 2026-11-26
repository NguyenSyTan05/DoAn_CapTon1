"use client";

import ChangePasswordCard from "@/components/shell/ChangePasswordCard";

export default function AdminChangePasswordPage() {
  return (
    <div style={{ padding: "28px 32px" }}>
      <h1 style={{ margin: "0 0 6px", fontSize: 24, color: "#0f172a" }}>Bảo mật tài khoản Quản trị</h1>
      <p style={{ margin: "0 0 20px", color: "#64748b", fontSize: 14 }}>
        Thay đổi mật khẩu đăng nhập tài khoản Quản trị viên định kỳ để đảm bảo an toàn hệ thống.
      </p>
      <ChangePasswordCard maxWidth={620} />
    </div>
  );
}
