import axios from "axios";

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1"]);

/**
 * Tự động ánh xạ địa chỉ Flask sang IP mạng LAN khi sinh viên mở web từ điện thoại
 * (ví dụ quét mã QR vào http://192.168.1.x:4000) kể cả khi .env.local để 127.0.0.1:5000.
 */
function resolveApiBaseUrl() {
  const configured = (process.env.NEXT_PUBLIC_API_BASE_URL || "").trim().replace(/\/$/, "");
  if (typeof window === "undefined") {
    return configured || "http://127.0.0.1:5000";
  }
  const pageHost = window.location.hostname;
  if (!configured) {
    return `${window.location.protocol}//${pageHost}:5000`;
  }
  try {
    const parsed = new URL(configured);
    if (LOOPBACK_HOSTS.has(parsed.hostname) && !LOOPBACK_HOSTS.has(pageHost)) {
      parsed.hostname = pageHost;
      return parsed.origin;
    }
  } catch {
    // Giữ nguyên nếu URL cấu hình tùy chỉnh
  }
  return configured;
}

const api = axios.create({
  baseURL: resolveApiBaseUrl(),
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use(
  (config) => {
    if (typeof window !== "undefined") {
      config.baseURL = resolveApiBaseUrl();
      const token = localStorage.getItem("token");
      if (token) config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

export default api;
