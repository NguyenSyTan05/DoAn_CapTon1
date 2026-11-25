"use client";

/**
 * Đọc phiên đăng nhập đã lưu trong localStorage ("token" + "user").
 * Token hết hạn (theo claim exp của JWT) được coi như chưa đăng nhập; việc xoá token cũ
 * làm trong effect/handler (clearExpiredSession), không làm trong lúc render.
 * Đây chỉ là kiểm tra phía trình duyệt để hiển thị; quyền thật do backend quyết định.
 */
import { useEffect, useSyncExternalStore } from "react";

export const ROLE_HOME: Record<string, string> = {
  sinh_vien: "/sinhvien",
  giang_vien: "/giangvien",
  admin: "/admin",
};

export type StoredSession = {
  token: string;
  user: { email?: string; full_name?: string; role?: string };
  home: string;
};

/** Thời điểm hết hạn (ms) theo claim exp; null nếu token không có exp; NaN nếu token hỏng. */
function tokenExpiry(token: string): number | null {
  try {
    const payload = JSON.parse(
      atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")),
    );
    return typeof payload.exp === "number" ? payload.exp * 1000 : null;
  } catch {
    return NaN;
  }
}

function tokenExpired(token: string): boolean {
  const exp = tokenExpiry(token);
  if (exp === null) return false;
  return Number.isNaN(exp) || exp <= Date.now();
}

/** Thuần (không ghi localStorage) — gọi được trong render/getSnapshot. */
export function getStoredSession(): StoredSession | null {
  try {
    const token = localStorage.getItem("token");
    const user = JSON.parse(localStorage.getItem("user") || "null");
    const home = user && ROLE_HOME[user.role];
    if (!token || !home || tokenExpired(token)) return null;
    return { token, user, home };
  } catch {
    return null;
  }
}

/** Xoá token/user đã hết hạn (hoặc hỏng). Chỉ gọi trong effect hoặc handler. */
export function clearExpiredSession(): void {
  try {
    const token = localStorage.getItem("token");
    if (token && tokenExpired(token)) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
    }
  } catch {
    /* localStorage không dùng được */
  }
}

// --- Hook theo dõi localStorage (đăng nhập/đăng xuất ở tab khác cũng cập nhật) ---
const MAX_TIMER_MS = 2_147_483_647; // giới hạn của setTimeout

const subscribe = (onChange: () => void) => {
  let timer: number | undefined;
  // Hẹn giờ tới lúc token hết hạn để giao diện tự chuyển sang "chưa đăng nhập" khi tab vẫn mở.
  const arm = () => {
    window.clearTimeout(timer);
    timer = undefined;
    let exp: number | null = null;
    try {
      const token = localStorage.getItem("token");
      exp = token ? tokenExpiry(token) : null;
    } catch {
      exp = null;
    }
    if (exp === null || Number.isNaN(exp)) return;
    const delay = exp - Date.now();
    if (delay > 0) timer = window.setTimeout(handle, Math.min(delay + 50, MAX_TIMER_MS));
  };
  const handle = () => {
    arm();
    onChange();
  };
  window.addEventListener("storage", handle);
  arm();
  return () => {
    window.removeEventListener("storage", handle);
    window.clearTimeout(timer);
  };
};

// Snapshot là chuỗi để React so sánh ổn định giữa các lần render.
const getSnapshot = () => {
  const session = getStoredSession();
  return session ? JSON.stringify(session) : "";
};

export function useStoredSession(): StoredSession | null {
  const raw = useSyncExternalStore(subscribe, getSnapshot, () => "");
  // Hết hạn -> dọn localStorage ngoài lúc render
  useEffect(() => {
    if (!raw) clearExpiredSession();
  }, [raw]);
  return raw ? (JSON.parse(raw) as StoredSession) : null;
}
