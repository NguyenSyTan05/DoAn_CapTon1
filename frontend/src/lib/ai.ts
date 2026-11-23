/**
 * Địa chỉ backend AI (FastAPI) và phiên học hiện tại — gom về một chỗ thay vì viết cứng
 * `http://<host>:8000` ở nhiều file.
 *
 *  - NEXT_PUBLIC_AI_URL (tuỳ chọn): ví dụ http://192.168.1.9:8000. Mặc định dùng hostname
 *    đang mở trang với cổng 8000, để mở từ thiết bị khác trong mạng LAN vẫn gọi đúng máy chủ.
 *  - Phiên học lấy từ `?session=<id>` hoặc đường dẫn `/.../classroom/<id>`.
 */

export function aiHttp(): string {
  if (process.env.NEXT_PUBLIC_AI_URL) return process.env.NEXT_PUBLIC_AI_URL.replace(/\/$/, "");
  return typeof window !== "undefined"
    ? `http://${window.location.hostname}:8000`
    : "http://localhost:8000";
}

export function aiWs(): string {
  return aiHttp().replace(/^http/, "ws");
}

/** Chỉ gọi ở trình duyệt (trong effect/handler). */
export function currentSession(): string | null {
  if (typeof window === "undefined") return null;
  const fromQuery = new URLSearchParams(window.location.search).get("session");
  if (fromQuery) return fromQuery;
  const match = window.location.pathname.match(/\/classroom\/([^/]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

type Param = string | number | boolean | null | undefined;

/** Thêm query vào URL, bỏ qua giá trị rỗng/null. */
export function withParams(url: string, params: Record<string, Param>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  }
  const qs = query.toString();
  return qs ? `${url}${url.includes("?") ? "&" : "?"}${qs}` : url;
}

/** URL REST của backend AI, tự gắn phiên hiện tại. */
export function aiUrl(path: string): string {
  return withParams(`${aiHttp()}${path}`, { session: currentSession() });
}

/** URL WebSocket của backend AI, tự gắn phiên hiện tại. */
export function aiWsUrl(path: string, extra: Record<string, Param> = {}): string {
  return withParams(`${aiWs()}${path}`, { session: currentSession(), ...extra });
}
