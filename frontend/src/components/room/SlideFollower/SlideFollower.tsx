"use client";
import React, { useEffect, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import { FileText, Presentation } from 'lucide-react';
import { aiFetch, aiWsUrl } from '../../../lib/ai';
import styles from '../SlideViewer/SlideViewer.module.css';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface DeckState {
  has_file: boolean;
  filename: string;
  version: number;
  page: number;
}

const RECONNECT_MS = 2000;
const RESYNC_MS = 3000;

/**
 * [CUSTOM] Khung slide của SINH VIÊN: tải file PDF mà giảng viên chia sẻ (cùng phiên) và
 * tự chuyển theo số trang giảng viên đang mở. Sinh viên chỉ xem, không điều khiển.
 *
 * Độ bền: WebSocket /api/v1/ws/slides đẩy 'state' (đổi file / mới vào) và 'page' (chuyển slide);
 * nếu kết nối rơi thì tự nối lại, và cứ RESYNC_MS giây lại đọc GET /slides/state để sửa trang
 * bị lệch (không phụ thuộc vào việc không mất tin nhắn nào).
 */
export default function SlideFollower() {
  const [filename, setFilename] = useState('');
  const [page, setPage] = useState(1);
  const [numPages, setNumPages] = useState(0);
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  const versionRef = useRef(0);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let closed = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: number | undefined;
    let lastPushAt = 0; // thời điểm nhận tin đẩy gần nhất từ WebSocket

    const loadFile = async (version: number) => {
      try {
        const res = await aiFetch('/api/v1/slides/file', { cache: 'no-store' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blobUrl = URL.createObjectURL(await res.blob());
        if (closed) {
          URL.revokeObjectURL(blobUrl);
          return;
        }
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = blobUrl;
        versionRef.current = version;
        setNumPages(0);
        setFileUrl(blobUrl);
        setError('');
      } catch {
        if (!closed) setError('Không tải được slide của giảng viên.');
      }
    };

    const applyState = (state: DeckState) => {
      setPage(state.page);
      setFilename(state.filename);
      if (state.has_file && state.version !== versionRef.current) void loadFile(state.version);
    };

    const connect = () => {
      if (closed) return;
      ws = new WebSocket(aiWsUrl('/api/v1/ws/slides'));
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          lastPushAt = Date.now();
          if (msg.type === 'state') applyState(msg as DeckState);
          else if (msg.type === 'page') setPage(msg.page);
        } catch (err) {
          console.warn('Slide WebSocket parse error:', err);
        }
      };
      ws.onclose = () => {
        if (!closed) reconnectTimer = window.setTimeout(connect, RECONNECT_MS);
      };
    };
    connect();

    // Đồng bộ định kỳ: bỏ qua kết quả đọc nếu trong lúc chờ đã có tin đẩy mới hơn
    const resync = window.setInterval(async () => {
      const startedAt = Date.now();
      try {
        const res = await aiFetch('/api/v1/slides/state', { cache: 'no-store' });
        if (!res.ok || closed || lastPushAt > startedAt) return;
        applyState(await res.json());
      } catch {
        /* lượt sau thử lại */
      }
    }, RESYNC_MS);

    return () => {
      closed = true;
      window.clearTimeout(reconnectTimer);
      window.clearInterval(resync);
      ws?.close();
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current);
        urlRef.current = null;
      }
    };
  }, []);

  const shownPage = numPages ? Math.min(page, numPages) : page;

  return (
    <div className={styles.container}>
      <div className={styles.headerBadge}>
        <span className={styles.badgeTag}>
          <FileText className="w-3.5 h-3.5" /> SLIDES
        </span>
        {fileUrl && (
          <>
            <span className={styles.badgeDivider}>|</span>
            <span className={styles.badgeSharer}>
              {shownPage} / {numPages || '?'}
            </span>
          </>
        )}
      </div>

      <div className={styles.contentArea}>
        {!fileUrl ? (
          <div className={styles.emptyBox}>
            <div className={styles.iconWrapper}>
              <Presentation className="w-10 h-10 stroke-[1.5]" />
            </div>
            <h3 className={styles.emptyTitle}>Giảng viên chưa chia sẻ slide</h3>
            <p className={styles.emptyDesc}>
              {error || 'Slide sẽ tự hiện ở đây khi giảng viên tải lên, và tự chuyển trang theo giảng viên.'}
            </p>
          </div>
        ) : (
          <div className={styles.viewerWrapper}>
            <div className={styles.pdfPage}>
              <Document
                file={fileUrl}
                onLoadSuccess={({ numPages: total }) => setNumPages(total)}
                loading={<p className={styles.loadingText}>Đang tải slide...</p>}
                error={<p className={styles.loadingText}>Không hiển thị được file PDF.</p>}
              >
                <Page pageNumber={shownPage} width={640} />
              </Document>
            </div>
            <div className={styles.navBar}>
              <span className={styles.pageIndicator}>
                {filename ? `${filename} · ` : ''}Slide {shownPage} / {numPages || '?'} (theo giảng viên)
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
