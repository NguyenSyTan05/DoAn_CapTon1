"use client";
import { aiUrl } from '../../../lib/ai';
import React, { useCallback, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import { Upload, ChevronLeft, ChevronRight, FileText } from 'lucide-react';
import styles from './SlideViewer.module.css';

// [EXISTING LIBRARY: pdf.js, qua react-pdf] Render PDF trong trình duyệt —
// pdf.js chạy phần parse/render nặng trong 1 web worker riêng.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface SlideViewerProps {
  onSlideChange?: (slideNumber: number) => void;
}

// [CUSTOM] Thay thế LiveScreenShare (trước đây chỉ là UI trang trí, không
// có logic thật). Giảng viên tự upload PDF thay vì screen-share — chuyển
// slide là một sự kiện CHẮC CHẮN (đổi số trang), không cần computer vision
// để "đoán" đổi slide. Mỗi lần chuyển slide, gửi 1 sự kiện nhẹ lên backend
// (POST /api/v1/slides/event) để sau này đối chiếu với timestamp câu hỏi
// — phục vụ biểu đồ "mức độ tương tác theo từng slide" trên Dashboard.
export default function SlideViewer({ onSlideChange }: SlideViewerProps) {
  const [file, setFile] = useState<File | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  // Trạng thái chia sẻ slide cho sinh viên của phiên hiện tại
  const [shareStatus, setShareStatus] = useState<'idle' | 'uploading' | 'shared' | 'failed'>('idle');

  const reportSlideChange = useCallback((slideNumber: number) => {
    onSlideChange?.(slideNumber);
    fetch(aiUrl("/api/v1/slides/event"), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slide_number: slideNumber }),
    }).catch((error) => console.error('Cannot report slide event:', error));
  }, [onSlideChange]);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0];
    if (selected) {
      setFile(selected);
      setNumPages(0);
      setPageNumber(1);
      void shareFile(selected);
    }
  };

  // Gửi file PDF lên backend (theo ?session=) để sinh viên tải về và theo số trang
  const shareFile = async (pdf: File) => {
    setShareStatus('uploading');
    try {
      const res = await fetch(aiUrl('/api/v1/slides/file'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/pdf', 'X-Filename': encodeURIComponent(pdf.name) },
        body: pdf,
      });
      setShareStatus(res.ok ? 'shared' : 'failed');
    } catch {
      setShareStatus('failed');
    }
  };

  // react-pdf (nhất là ở chế độ dev/StrictMode) có thể gọi onLoadSuccess nhiều lần cho cùng một
  // file. Nếu mỗi lần đều báo "slide 1" thì server (và sinh viên) bị kéo về trang 1 ngay sau mỗi
  // lần giảng viên chuyển slide. Chỉ báo trang 1 MỘT lần cho mỗi file được mở.
  const reportedFileRef = useRef<File | null>(null);

  const handleLoadSuccess = ({ numPages: total }: { numPages: number }) => {
    setNumPages(total);
    if (reportedFileRef.current !== file) {
      reportedFileRef.current = file;
      reportSlideChange(1);
    }
  };

  const goToPage = (next: number) => {
    if (next < 1 || next > numPages) return;
    setPageNumber(next);
    reportSlideChange(next);
  };

  return (
    <div className={styles.container}>
      <div className={styles.headerBadge}>
        <span className={styles.badgeTag}>
          <FileText className="w-3.5 h-3.5" /> SLIDES
        </span>
        {file && (
          <>
            <span className={styles.badgeDivider}>|</span>
            <span className={styles.badgeSharer}>
              {pageNumber} / {numPages || "?"}
            </span>
            <span className={styles.badgeDivider}>|</span>
            <span className={styles.badgeSharer}>
              {shareStatus === 'uploading' && 'Đang chia sẻ cho sinh viên...'}
              {shareStatus === 'shared' && 'Đã chia sẻ cho sinh viên'}
              {shareStatus === 'failed' && 'Chia sẻ thất bại'}
            </span>
          </>
        )}
      </div>

      <div className={styles.contentArea}>
        {!file ? (
          <div className={styles.emptyBox}>
            <div className={styles.iconWrapper}>
              <Upload className="w-10 h-10 stroke-[1.5]" />
            </div>
            <h3 className={styles.emptyTitle}>No slides uploaded</h3>
            <p className={styles.emptyDesc}>
              Upload a PDF to present slides to the class.
            </p>
            <label className={styles.shareBtn}>
              <Upload className="w-4 h-4" /> Upload PDF
              <input
                type="file"
                accept="application/pdf"
                onChange={handleFileChange}
                hidden
              />
            </label>
          </div>
        ) : (
          <div className={styles.viewerWrapper}>
            <div className={styles.pdfPage}>
              <Document
                file={file}
                onLoadSuccess={handleLoadSuccess}
                loading={<p className={styles.loadingText}>Loading PDF...</p>}
              >
                <Page pageNumber={pageNumber} width={640} />
              </Document>
            </div>

            <div className={styles.navBar}>
              <button
                type="button"
                onClick={() => goToPage(pageNumber - 1)}
                disabled={pageNumber <= 1}
                className={styles.navBtn}
              >
                <ChevronLeft className="w-4 h-4" /> Prev
              </button>

              <span className={styles.pageIndicator}>
                Slide {pageNumber} / {numPages}
              </span>

              <button
                type="button"
                onClick={() => goToPage(pageNumber + 1)}
                disabled={pageNumber >= numPages}
                className={styles.navBtn}
              >
                Next <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
