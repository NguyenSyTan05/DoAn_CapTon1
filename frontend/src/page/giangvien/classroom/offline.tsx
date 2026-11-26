"use client";

import axios from "axios";
import {
  ArrowLeft,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Expand,
  Loader2,
  MessageSquareText,
  Mic,
  MicOff,
  Plus,
  Presentation,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "@/lib/router-compat";
import { aiFetch, aiWsUrl } from "../../../lib/ai";
import api from "../../../services/api";
import styles from "./offline.module.css";

type SessionStatus = "upcoming" | "live" | "ended";
type LanguageDirection = "vi-en" | "en-vi";

type OfflineSession = {
  id: string;
  title: string;
  status: SessionStatus;
  deliveryMode: "ONLINE" | "OFFLINE" | null;
  classCode: string;
  className: string;
  studentCount: number;
  totalQuestions: number;
  unansweredQuestions: number;
};

type SessionMaterial = {
  fileId: string;
  fileName: string;
  extension: string;
  firstSlide: {
    number: number;
    title: string | null;
    text: string | null;
    imageUrl: string | null;
  } | null;
  previewUrl: string | null;
};

const errorMessage = (error: unknown, fallback: string) => {
  const responseData = axios.isAxiosError<{ message?: string; msg?: string }>(
    error,
  )
    ? error.response?.data
    : undefined;
  return responseData?.message || responseData?.msg || fallback;
};

export default function OfflineClassroomPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState<OfflineSession | null>(null);
  const [material, setMaterial] = useState<SessionMaterial | null>(null);
  const [previewSrc, setPreviewSrc] = useState("");
  const [slidePage, setSlidePage] = useState(1);
  const [isLoading, setIsLoading] = useState(Boolean(sessionId));
  const [pageError, setPageError] = useState(
    sessionId ? "" : "Không có mã phiên học trong địa chỉ trang.",
  );
  const [languageDirection, setLanguageDirection] =
    useState<LanguageDirection>("vi-en");
  const [showBilingual, setShowBilingual] = useState(true);
  const [showExitMenu, setShowExitMenu] = useState(false);
  const [isEndingSession, setIsEndingSession] = useState(false);
  const [presentationError, setPresentationError] = useState("");

  // Tích hợp thu âm thật & phụ đề song ngữ thời gian thực cho phòng Offline
  const [isMicOn, setIsMicOn] = useState(false);
  const [latestOriginal, setLatestOriginal] = useState("");
  const [latestTranslated, setLatestTranslated] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);

  const languageDirRef = useRef<LanguageDirection>("vi-en");

  const stopRecording = useCallback(() => {
    workletRef.current?.disconnect();
    workletRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "end" }));
    }
    setIsMicOn(false);
  }, []);

  const toggleLanguageDirection = () => {
    const nextDir: LanguageDirection = languageDirection === "vi-en" ? "en-vi" : "vi-en";
    languageDirRef.current = nextDir;
    setLanguageDirection(nextDir);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          action: "set_language",
          language: nextDir === "vi-en" ? "vi" : "en",
        }),
      );
    }
  };

  useEffect(() => {
    if (!sessionId) return;
    let active = true;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (!active) return;
      const spokenLang = languageDirRef.current === "vi-en" ? "vi" : "en";
      ws = new WebSocket(
        aiWsUrl("/api/v1/ws/live-translate", {
          session: sessionId,
          role: "lecturer",
          fmt: "pcm32",
          progressive: 1,
          lang: spokenLang,
        }),
      );
      ws.onopen = () => {
        if (active && ws?.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              action: "set_language",
              language: languageDirRef.current === "vi-en" ? "vi" : "en",
            }),
          );
        }
      };
      ws.onmessage = (event) => {
        if (!active) return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "final") {
            setLatestOriginal(msg.original_text || "");
            setLatestTranslated("…");
          } else if (msg.type === "translation") {
            setLatestTranslated(msg.translated_text || "");
          } else if (msg.type === "result") {
            setLatestOriginal(msg.original_text || "");
            setLatestTranslated(msg.translated_text || "");
          }
        } catch {
          /* ignore */
        }
      };
      ws.onclose = (ev) => {
        if (!active || ev.code === 1008) return;
        reconnectTimer = setTimeout(connect, 2000);
      };
      wsRef.current = ws;
    };

    connect();
    return () => {
      active = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      stopRecording();
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        ws.close();
      }
    };
  }, [sessionId, stopRecording]);

  const toggleMic = async () => {
    if (isMicOn) {
      stopRecording();
      return;
    }
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: { ideal: 16000 },
        },
      });
      try {
        ctx = new AudioContext({ sampleRate: 16000 });
      } catch {
        ctx = new AudioContext();
      }
      const source = ctx.createMediaStreamSource(stream);
      await ctx.audioWorklet.addModule("/pcm-processor.js");
      if (ctx.state === "suspended") await ctx.resume();
      const node = new AudioWorkletNode(ctx, "pcm-processor");
      node.port.onmessage = (ev) => {
        if (ev.data?.type === "pcm_data" && wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(ev.data.buffer);
        }
      };
      const mute = ctx.createGain();
      mute.gain.value = 0;
      source.connect(node);
      node.connect(mute);
      mute.connect(ctx.destination);

      streamRef.current = stream;
      audioCtxRef.current = ctx;
      workletRef.current = node;
      setIsMicOn(true);
      setShowBilingual(true);
      setPageError("");
    } catch {
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close().catch(() => {});
      setPageError("Không bật được micro. Vui lòng cấp quyền truy cập micro trên trình duyệt.");
    }
  };

  const changeSlidePage = (nextPage: number) => {
    const clamped = Math.max(1, nextPage);
    setSlidePage(clamped);
    if (sessionId) {
      void aiFetch(`/api/v1/slides/event?session=${encodeURIComponent(sessionId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slide_number: clamped }),
      }).catch(() => {});
    }
  };

  const startPresentation = async () => {
    const slideCanvas = document.querySelector<HTMLElement>(
      `.${styles.slideCanvas}`,
    );
    if (!slideCanvas?.requestFullscreen) {
      setPresentationError("Trình duyệt này không hỗ trợ trình chiếu toàn màn hình.");
      return;
    }
    try {
      await slideCanvas.requestFullscreen();
      setPresentationError("");
    } catch {
      setPresentationError("Không thể bật chế độ trình chiếu toàn màn hình.");
    }
  };

  const loadSession = useCallback(async () => {
    if (!sessionId) return;
    try {
      const { data } = await api.get<{ session: OfflineSession }>(
        `/auth/lecturer/sessions/${encodeURIComponent(sessionId)}`,
      );
      setSession(data.session);
      setPageError("");
    } catch (error: unknown) {
      setPageError(errorMessage(error, "Không thể tải thông tin buổi học."));
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    const initialLoad = window.setTimeout(() => void loadSession(), 0);
    const timer = window.setInterval(() => void loadSession(), 15000);
    return () => {
      window.clearTimeout(initialLoad);
      window.clearInterval(timer);
    };
  }, [loadSession, sessionId]);

  useEffect(() => {
    let active = true;
    if (!sessionId) {
      return () => {
        active = false;
      };
    }

    api
      .get<{ material: SessionMaterial | null }>(
        `/auth/lecturer/sessions/${encodeURIComponent(sessionId)}/materials`,
      )
      .then(({ data }) => {
        if (active) setMaterial(data.material);
      })
      .catch((error: unknown) => {
        if (active) {
          setPageError(
            errorMessage(error, "Không thể tải bài giảng của buổi học."),
          );
        }
      });

    return () => {
      active = false;
    };
  }, [sessionId]);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    const previewUrl = material?.previewUrl;
    if (!previewUrl?.startsWith("/")) {
      return () => {
        active = false;
      };
    }

    api
      .get(previewUrl, { responseType: "blob" })
      .then(({ data }) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(data);
        setPreviewSrc(objectUrl);
        if (
          sessionId &&
          data instanceof Blob &&
          data.size > 0 &&
          data.size <= 20 * 1024 * 1024 &&
          material?.extension?.toLowerCase() === "pdf"
        ) {
          void aiFetch(`/api/v1/slides/file?session=${encodeURIComponent(sessionId)}`, {
            method: "POST",
            headers: {
              "Content-Type": "application/pdf",
              "x-filename": encodeURIComponent(material.fileName || "slides.pdf"),
            },
            body: data,
          }).catch(() => {});
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setPageError(
            errorMessage(error, "Không thể mở trang đầu bài giảng."),
          );
        }
      });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [material?.previewUrl, material?.extension, material?.fileName, sessionId]);

  const handleEndSession = async () => {
    if (
      !sessionId ||
      !window.confirm("Kết thúc buổi học sẽ ngắt phiên của cả lớp. Tiếp tục?")
    ) {
      return;
    }
    stopRecording();
    setIsEndingSession(true);
    try {
      await api.post(
        `/auth/lecturer/sessions/${encodeURIComponent(sessionId)}/end`,
      );
      navigate(`/giangvien/summary?session=${encodeURIComponent(sessionId)}`, { replace: true });
    } catch (error: unknown) {
      setPageError(errorMessage(error, "Không thể kết thúc buổi học."));
      setIsEndingSession(false);
    }
  };

  const renderedPreview = material?.firstSlide?.imageUrl ? (
    <img
      className={styles.slideImage}
      src={material.firstSlide.imageUrl}
      alt={material.firstSlide.title || "Slide bài giảng"}
    />
  ) : previewSrc ? (
    <iframe
      key={slidePage}
      className={styles.slidePdf}
      src={`${previewSrc}#page=${slidePage}&toolbar=0&navpanes=0`}
      title={`Slide bài giảng: ${material?.fileName || ""}`}
    />
  ) : material?.firstSlide?.text ? (
    <div className={styles.slideText}>
      <h2>{material.firstSlide.title || "Bài giảng"}</h2>
      <p>{material.firstSlide.text}</p>
    </div>
  ) : (
    <div className={styles.emptySlide}>
      <Presentation size={56} />
      <strong>
        {material
          ? "Tài liệu chưa có bản xem trước"
          : "Chưa có bài giảng cho buổi học này"}
      </strong>
      <span>
        {material?.fileName || "Thêm file bài giảng từ trang chi tiết buổi học."}
      </span>
    </div>
  );

  return (
    <main className={styles.page}>
      <header className={styles.topBar}>
        <button
          type="button"
          className={styles.backButton}
          onClick={() => {
            stopRecording();
            navigate(`/giangvien/classroom/${encodeURIComponent(sessionId || "")}`);
          }}
        >
          <ArrowLeft size={17} />
          <span>Rời phòng học</span>
        </button>
        <div className={styles.sessionIdentity}>
          <span className={styles.liveDot} />
          <span>{session?.classCode || "Phòng học offline"}</span>
          <span className={styles.identityDivider}>/</span>
          <strong>{session?.title || "Đang tải buổi học..."}</strong>
        </div>
        <div className={styles.topRight}>
          <span className={styles.modeBadge}>Học offline</span>
          <button
            type="button"
            className={styles.languageSelect}
            onClick={() => setShowBilingual((visible) => !visible)}
            aria-expanded={showBilingual}
          >
            {showBilingual ? "Tắt song ngữ" : "Bật song ngữ"}
          </button>
        </div>
      </header>

      {pageError && (
        <div className={styles.pageError} role="alert">
          {pageError}
          <button type="button" onClick={() => setPageError("")} aria-label="Đóng">
            <X size={16} />
          </button>
        </div>
      )}
      {presentationError && (
        <div className={styles.pageError} role="alert">
          {presentationError}
          <button
            type="button"
            onClick={() => setPresentationError("")}
            aria-label="Đóng"
          >
            <X size={16} />
          </button>
        </div>
      )}
      <section className={styles.classroom}>
        <div className={styles.presentationPanel}>
          <div className={styles.presentationToolbar}>
            <span className={styles.presentationTitle}>
              {material?.fileName || "Bài giảng"}
            </span>
            <div className={styles.presentationActions}>
              {previewSrc && (
                <>
                  <button
                    type="button"
                    className={styles.presentButton}
                    onClick={() => changeSlidePage(slidePage - 1)}
                    disabled={slidePage <= 1}
                    aria-label="Trang trước"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span className={styles.slideCount}>Trang {slidePage}</span>
                  <button
                    type="button"
                    className={styles.presentButton}
                    onClick={() => changeSlidePage(slidePage + 1)}
                    aria-label="Trang sau"
                  >
                    <ChevronRight size={16} />
                  </button>
                </>
              )}
              {!previewSrc && (
                <span className={styles.slideCount}>
                  {material ? "Trang 1" : "Chưa có slide"}
                </span>
              )}
              <button
                type="button"
                className={styles.presentButton}
                onClick={() => void startPresentation()}
                title="Chỉ trình chiếu slide; nhấn Esc để thoát"
                aria-label="Trình chiếu riêng slide toàn màn hình"
              >
                <Expand size={16} />
                <span>Trình chiếu</span>
              </button>
            </div>
          </div>
          <div className={styles.slideCanvas}>
            {isLoading ? (
              <div className={styles.loadingState}>
                <Loader2 className={styles.spinner} size={28} />
                <span>Đang tải phòng học...</span>
              </div>
            ) : (
              renderedPreview
            )}
          </div>
          {showBilingual && (
            <section className={styles.subtitlePanel} aria-live="polite">
              <div className={styles.subtitleHeading}>
                <span className={styles.subtitleLiveDot} />
                <strong>Phụ đề song ngữ trực tiếp</strong>
                <button
                  type="button"
                  className={styles.directionButton}
                  onClick={toggleLanguageDirection}
                >
                  {languageDirection === "vi-en" ? "VI → EN" : "EN → VI"}
                  <ChevronDown size={14} />
                </button>
              </div>
              <div className={styles.bilingualText}>
                <div>
                  <strong>
                    {languageDirection === "vi-en" ? "Lời gốc (VI)" : "Original (EN)"}
                  </strong>
                  <p>
                    {latestOriginal ||
                      (isMicOn
                        ? "Đang lắng nghe lời giảng..."
                        : "Bấm nút Mic để bắt đầu thu âm & phát phụ đề trực tiếp.")}
                  </p>
                </div>
                <div>
                  <strong>
                    {languageDirection === "vi-en" ? "Bản dịch (EN)" : "Bản dịch (VI)"}
                  </strong>
                  <p>
                    {latestTranslated ||
                      "Bản dịch song ngữ sẽ hiển thị tức thì tại đây."}
                  </p>
                </div>
              </div>
            </section>
          )}
        </div>

        <aside className={styles.sidePanel}>
          <div className={styles.sidePanelHeader}>
            <div>
              <span className={styles.eyebrow}>PHÒNG HỌC</span>
              <h1>{session?.className || "Lớp học"}</h1>
            </div>
            <span className={styles.statusBadge}>
              <span className={styles.liveDot} />
              {session?.status === "live"
                ? "Đang diễn ra"
                : session?.status || "Đang tải"}
            </span>
          </div>
          <button
            type="button"
            className={styles.micSetupButton}
            onClick={() => void toggleMic()}
          >
            {isMicOn ? <Mic size={17} /> : <MicOff size={17} />}
            {isMicOn ? "Đang thu âm trực tiếp" : "Kết nối mic"}
            <span>{isMicOn ? "Đang bật" : "Chưa bật"}</span>
          </button>
          <div className={styles.privacyNote}>
            {isMicOn ? <Mic size={15} /> : <MicOff size={15} />}
            {isMicOn
              ? "Đang truyền âm thanh tới bộ nhận dạng STT & phát phụ đề cho cả lớp."
              : "Mic đang tắt. Bấm để phát phụ đề trực tiếp cho sinh viên."}
          </div>
          {material && (
            <div className={styles.materialInfo}>
              <Presentation size={17} />
              <span>{material.fileName}</span>
            </div>
          )}
          {sessionId && (
            <button
              type="button"
              className={styles.micSetupButton}
              onClick={() =>
                navigate(`/giangvien/summary?session=${encodeURIComponent(sessionId)}`)
              }
            >
              <Sparkles size={17} />
              Tóm tắt bài giảng
              <span>AI</span>
            </button>
          )}
        </aside>
      </section>

      <footer className={styles.controlBar}>
        <div className={styles.controlGroup}>
          <button
            type="button"
            className={styles.chatButton}
            onClick={() =>
              navigate(
                `/giangvien/classroom/${encodeURIComponent(sessionId || "")}/chat`,
              )
            }
            aria-label="Mở chat của buổi học"
          >
            <MessageSquareText size={19} />
            <span>Chat</span>
          </button>
          <button
            type="button"
            className={styles.controlButton}
            onClick={() => void toggleMic()}
            aria-label="Microphone"
          >
            {isMicOn ? <Mic size={20} color="#22c55e" /> : <MicOff size={20} />}
            <span>{isMicOn ? "Tắt Mic" : "Bật Mic"}</span>
          </button>
        </div>
        <div className={styles.controlDivider} />
        <div className={styles.controlGroup}>
          <div className={styles.statItem}>
            <Users size={20} />
            <span className={styles.statValue}>
              {session?.studentCount ?? 0}
            </span>
            <span>Sinh viên</span>
          </div>
          <div className={styles.statItem}>
            <MessageSquareText size={20} />
            <span className={styles.statValue}>
              {session?.totalQuestions ?? 0}
            </span>
            <span>Câu hỏi</span>
          </div>
          <div className={styles.statItem}>
            <CircleHelp size={20} />
            <span className={styles.statValue}>
              {session?.unansweredQuestions ?? 0}
            </span>
            <span>Chưa trả lời</span>
          </div>
        </div>
        <div className={styles.controlDivider} />
        <div className={styles.controlGroup}>
          <button
            type="button"
            className={styles.quickQuestionButton}
            onClick={() =>
              navigate(
                `/giangvien/classroom/${encodeURIComponent(sessionId || "")}/cauhoi`,
              )
            }
            disabled={session?.status !== "live"}
          >
            <Plus size={19} />
            <span>Tạo câu hỏi nhanh</span>
          </button>
          <div className={styles.exitContainer}>
            <button
              type="button"
              className={styles.exitButton}
              onClick={() => setShowExitMenu((visible) => !visible)}
              aria-expanded={showExitMenu}
            >
              Thoát <ChevronDown size={15} />
            </button>
            {showExitMenu && (
              <div className={styles.exitMenu}>
                <button
                  type="button"
                  onClick={() => void handleEndSession()}
                  disabled={isEndingSession}
                >
                  {isEndingSession ? (
                    <Loader2 size={16} className={styles.spinner} />
                  ) : (
                    <X size={16} />
                  )}
                  Kết thúc & Xem Tóm tắt
                </button>
                <button
                  type="button"
                  onClick={() => {
                    stopRecording();
                    navigate(
                      `/giangvien/classroom/${encodeURIComponent(sessionId || "")}`,
                    );
                  }}
                >
                  <ArrowLeft size={16} />
                  Rời khỏi lớp học
                </button>
              </div>
            )}
          </div>
        </div>
      </footer>
    </main>
  );
}
