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

/** Header xác thực cho backend AI: cùng JWT Flask lưu ở localStorage("token"). */
export function aiAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = window.localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ---- Thông báo lỗi quyền vào phòng (dùng chung, hiển thị bởi components/shell/AiAccessNotice) ----

const AI_ACCESS_MESSAGES = {
  missingSession: "Thiếu phiên học — hãy vào phòng từ lớp học.",
  invalidSession: "Mã phiên học không hợp lệ — hãy vào phòng từ lớp học.",
  sessionClosed: "Phiên học đã kết thúc hoặc bị huỷ.",
  sessionNotFound: "Không tìm thấy phiên học.",
  sessionForbidden: "Bạn không có quyền vào phòng này.",
  roleForbidden: "Bạn không có quyền thực hiện thao tác này trong phòng học.",
};

// Route REST theo phòng (cần ?session=); /questions/aggregate và /translate chỉ cần token.
const ROOM_PATH = /^\/api\/v1\/(answers|slides|questions(?!\/aggregate))(\/|\?|$)/;

let aiAccessMessage = "";
let redirectingToLogin = false;
const aiAccessListeners = new Set<() => void>();

function setAiAccessMessage(message: string): void {
  if (message === aiAccessMessage) return;
  aiAccessMessage = message;
  aiAccessListeners.forEach((listener) => listener());
}

export function subscribeAiAccessMessage(listener: () => void): () => void {
  aiAccessListeners.add(listener);
  return () => {
    aiAccessListeners.delete(listener);
  };
}

export function getAiAccessMessage(): string {
  return aiAccessMessage;
}

export function clearAiAccessMessage(): void {
  setAiAccessMessage("");
}

/** true nếu mã lỗi này là lỗi xác thực/quyền mà aiFetch đã tự báo cho người dùng. */
export function isAiAccessStatus(status: number): boolean {
  return status === 401 || status === 403 || status === 404 || status === 422;
}

async function reportAiAccessError(path: string, res: Response): Promise<void> {
  if (res.status === 401) {
    // Token hết hạn/bị thu hồi: xoá phiên đăng nhập và quay về trang đăng nhập.
    if (redirectingToLogin) return;
    redirectingToLogin = true;
    window.localStorage.removeItem("token");
    window.localStorage.removeItem("user");
    window.location.replace("/login?expired=1");
    return;
  }
  if (!ROOM_PATH.test(path)) return;

  let detail: unknown = null;
  try {
    detail = (await res.json())?.detail;
  } catch {
    /* không phải JSON */
  }
  const code = detail && typeof detail === "object" ? (detail as { code?: unknown }).code : undefined;

  if (res.status === 403) {
    setAiAccessMessage(
      code === "session_closed"
        ? AI_ACCESS_MESSAGES.sessionClosed
        : code === "role_forbidden"
          ? AI_ACCESS_MESSAGES.roleForbidden
          : AI_ACCESS_MESSAGES.sessionForbidden,
    );
  } else if (res.status === 404 && code === "session_not_found") {
    setAiAccessMessage(AI_ACCESS_MESSAGES.sessionNotFound);
  } else if (res.status === 422 && typeof detail === "string") {
    // detail là chuỗi khi do kiểm tra phiên (core/auth.py); lỗi dữ liệu của pydantic là mảng.
    setAiAccessMessage(currentSession() ? AI_ACCESS_MESSAGES.invalidSession : AI_ACCESS_MESSAGES.missingSession);
  }
}

/**
 * fetch() tới REST của backend AI: tự gắn ?session=<phiên hiện tại> và Authorization: Bearer.
 * Mọi lời gọi REST tới ai-service nên đi qua hàm này.
 * Lỗi 401/403/404/422 về phiên học được tự báo bằng thông báo tiếng Việt (401: về /login?expired=1);
 * Response vẫn được trả lại nguyên vẹn cho nơi gọi.
 */
export async function aiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  for (const [key, value] of Object.entries(aiAuthHeaders())) {
    if (!headers.has(key)) headers.set(key, value);
  }
  const res = await fetch(aiUrl(path), { ...init, headers });
  if (typeof window !== "undefined" && isAiAccessStatus(res.status)) {
    void reportAiAccessError(path, res.clone()).catch(() => {});
  }
  return res;
}

/** URL WebSocket của backend AI, tự gắn phiên hiện tại. */
export function aiWsUrl(path: string, extra: Record<string, Param> = {}): string {
  return withParams(`${aiWs()}${path}`, { session: currentSession(), ...extra });
}
