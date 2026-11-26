"use client";

import React, { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { useRouter } from 'next/navigation';
import authService from '../../services/auth.service';
import { useStudentSession } from '../../page/sinhvien/useStudentSession';
import Header from '../../components/layout/Header/Header';
import Message from '../../components/room/Message/Meesage';
import QAToast from '../../components/room/QAToast/QAToast';
import Transcript from '../../components/room/Transcript/Transcript';
import UserParticipant from '../../components/room/UserParticipant/UserParticipant';
import BottomControles from '../../components/layout/BottomControles/BottomControles';
import { aiFetch, aiWsUrl, currentSession } from '../../lib/ai';

// react-pdf dùng window/document nên chỉ được tải ở trình duyệt (không render phía server)
const SlideViewer = dynamic(() => import('../../components/room/SlideViewer/SlideViewer'), { ssr: false });
const SlideFollower = dynamic(() => import('../../components/room/SlideFollower/SlideFollower'), { ssr: false });

import type { User, ChatMessage, TranScript } from '../../types';
import styles from './page.module.css';

export interface QuestionItem {
  id: string;
  text: string;
  timestamp: string;
}

type SpeechLang = 'auto' | 'vi' | 'en';
type RoomRole = 'lecturer' | 'student';

const isStudentRole = (role?: string) => role === 'sinh_vien' || role === 'student';

// Tin nhắn từ backend (giao thức progressive, xem be/modules/live_translate/router.py)
interface FinalMsg { type: 'final'; segment_id: number; original_text: string; source_lang: 'en' | 'vi'; timestamp: string }
interface TranslationMsg { type: 'translation'; segment_id: number; translated_text: string; target_lang: 'en' | 'vi' }
interface ResultMsg { type: 'result'; segment_id: number; original_text: string; translated_text: string; source_lang: 'en' | 'vi'; timestamp: string }
interface HistoryMsg { type: 'history'; items: ResultMsg[] }

const PENDING = '…';

export default function AIClassroomPage() {
  const [roomInfo] = useState({
    title: "Phân tích Kiến trúc Hệ thống Phân tán & AI",
    createdAt: new Date().toISOString(),
  });

  const [users] = useState<User[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [questions, setQuestions] = useState<QuestionItem[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [speechLang, setSpeechLang] = useState<SpeechLang>('vi');
  const router = useRouter();
  // Cùng một giao diện máy tính /room cho cả hai vai trò: giảng viên phát, sinh viên chỉ xem/hỏi
  const [role, setRole] = useState<RoomRole | null>(null);
  const [userName, setUserName] = useState('');
  const student = useStudentSession(sessionId, role === 'student');

  // [BUG FIX] `questions` state trước đây luôn khởi tạo rỗng — F5 trang là
  // state trong RAM mất, nhưng handleSendMessage() vẫn dùng state đó để ghi
  // đè "room_questions" trong localStorage (setItem, không phải append).
  // Load lại từ localStorage ngay khi mount để tránh ghi đè nhầm.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSessionId(currentSession());
      setRole(isStudentRole(authService.getCurrentUser()?.role) ? 'student' : 'lecturer');
      setUserName(authService.getCurrentUser()?.full_name ?? '');
      try {
        const saved = localStorage.getItem("room_questions");
        if (saved) {
          setQuestions(JSON.parse(saved));
        }
      } catch (error) {
        console.error("Cannot load room questions:", error);
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const [enTrans, setEnTrans] = useState<TranScript[]>([]);
  const [vnTrans, setVnTrans] = useState<TranScript[]>([]);

  const streamRef = useRef<MediaStream | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const isRecordingRef = useRef<boolean>(false);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const speechLangRef = useRef<SpeechLang>('vi');

  // ---- Phụ đề song ngữ -------------------------------------------------
  const addLine = (setter: React.Dispatch<React.SetStateAction<TranScript[]>>, id: string, text: string, timestamp: string) =>
    setter((prev) =>
      prev.some((l) => l.id === id)
        ? prev.map((l) => (l.id === id ? { ...l, text, timestamp } : l))
        : [...prev, { id, speaker: "Giảng viên", text, timestamp }]
    );
  const setLineText = (setter: React.Dispatch<React.SetStateAction<TranScript[]>>, id: string, text: string) =>
    setter((prev) => prev.map((l) => (l.id === id ? { ...l, text } : l)));

  const handleServerMessage = (data: FinalMsg | TranslationMsg | ResultMsg | HistoryMsg | { type: 'clear' }) => {
    if (data.type === 'clear') {
      setVnTrans([]);
      setEnTrans([]);
      return;
    }
    if (data.type === 'history') {
      setVnTrans([]);
      setEnTrans([]);
      data.items.forEach(handleServerMessage);
      return;
    }
    if (data.type === 'final') {
      const id = `seg-${data.segment_id}`;
      const [src, dst] = data.source_lang === 'en' ? [setEnTrans, setVnTrans] : [setVnTrans, setEnTrans];
      addLine(src, id, data.original_text, data.timestamp);   // lời gốc hiện ngay
      addLine(dst, id, PENDING, data.timestamp);              // chỗ chờ bản dịch
    } else if (data.type === 'translation') {
      const id = `seg-${data.segment_id}`;
      setLineText(data.target_lang === 'vi' ? setVnTrans : setEnTrans, id, data.translated_text || PENDING);
    } else if (data.type === 'result') {
      const id = `seg-${data.segment_id}`;
      const [src, dst] = data.source_lang === 'en' ? [setEnTrans, setVnTrans] : [setVnTrans, setEnTrans];
      addLine(src, id, data.original_text, data.timestamp);
      addLine(dst, id, data.translated_text, data.timestamp);
    }
  };

  // ---- Ghi âm: AudioWorklet gửi PCM 16 kHz (100 ms/gói) -----------------
  const stopRecording = () => {
    isRecordingRef.current = false;
    workletRef.current?.disconnect();
    workletRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    // Báo backend nhận dạng nốt câu đang dở
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "end" }));
    }
  };

  useEffect(() => {
    let isSubscribed = true;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    const base = process.env.NEXT_PUBLIC_WS_URL; // tương thích cấu hình cũ (đã gồm đường dẫn đầy đủ)
    const asStudent = isStudentRole(authService.getCurrentUser()?.role);

    const connect = () => {
      if (!isSubscribed) return;
      // Sinh viên chỉ nhận phụ đề (viewer); giảng viên gửi PCM 16 kHz
      const params = asStudent
        ? { role: "viewer", progressive: 1 }
        : { role: "lecturer", fmt: "pcm32", progressive: 1, lang: speechLangRef.current };
      const token = typeof window !== "undefined" ? window.localStorage.getItem("token") : null;
      const url = base
        ? `${base}${base.includes('?') ? '&' : '?'}${new URLSearchParams({
            ...(currentSession() ? { session: currentSession()! } : {}),
            ...(token ? { token } : {}),
            ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])),
          })}`
        : aiWsUrl("/api/v1/ws/live-translate", params);
      ws = new WebSocket(url);

      ws.onopen = () => {
        if (isSubscribed) {
          console.log("🟢 WebSocket Connected");
          if (!asStudent && ws?.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: "set_language", language: speechLangRef.current }));
          }
        }
      };

      ws.onmessage = (event) => {
        if (!isSubscribed) return;
        try {
          handleServerMessage(JSON.parse(event.data));
        } catch (err) {
          console.warn("Lỗi phân tích WebSocket:", err);
        }
      };

      ws.onclose = (event) => {
        if (!isSubscribed || event.code === 1008) return;
        reconnectTimer = setTimeout(connect, 1500);
      };

      wsRef.current = ws;
    };

    const connectTimer = setTimeout(connect, 0);

    return () => {
      isSubscribed = false;
      clearTimeout(connectTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      stopRecording();
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        ws.close();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startRecording = async (): Promise<boolean> => {
    if (isRecordingRef.current) return true;
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    try {
      // Bật đầy đủ WebRTC echoCancellation + noiseSuppression + autoGainControl
      // để khử tiếng xì xào nền trong phòng họp và giữ giọng nói chính xác.
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          sampleRate: { ideal: 16000 },
        },
      });
      let source: MediaStreamAudioSourceNode;
      try {
        ctx = new AudioContext({ sampleRate: 16000 });
        source = ctx.createMediaStreamSource(stream);
      } catch {
        ctx?.close().catch(() => {});
        ctx = new AudioContext();
        source = ctx.createMediaStreamSource(stream);
      }
      await ctx.audioWorklet.addModule("/pcm-processor.js");
      if (ctx.state === "suspended") {
        await ctx.resume();
      }
      const node = new AudioWorkletNode(ctx, "pcm-processor");
      node.port.onmessage = (event) => {
        if (event.data?.type === "pcm_data" && wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(event.data.buffer); // Float32 LE, 16 kHz, mono
        }
      };
      // Nối qua gain 0 để trình duyệt luôn kéo dữ liệu qua worklet mà không phát tiếng ra loa
      const mute = ctx.createGain();
      mute.gain.value = 0;
      source.connect(node);
      node.connect(mute);
      mute.connect(ctx.destination);

      streamRef.current = stream;
      audioCtxRef.current = ctx;
      workletRef.current = node;
      isRecordingRef.current = true;
      return true;
    } catch (err) {
      stream?.getTracks().forEach((track) => track.stop());
      ctx?.close().catch(() => {});
      console.error("Lỗi Mic:", err);
      alert("Không bật được micro. Hãy cho phép trình duyệt dùng micro (biểu tượng ổ khóa cạnh địa chỉ) rồi thử lại.");
      return false;
    }
  };

  const handleMicToggle = async (isMuted: boolean): Promise<boolean> => {
    if (isMuted) {
      stopRecording();
      return true;
    }
    return startRecording();
  };

  const changeSpeechLang = (value: SpeechLang) => {
    setSpeechLang(value);
    speechLangRef.current = value;
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "set_language", language: value }));
    }
  };

  const handleSendMessage = (content: string) => {
    if (!content.trim()) return;
    const isoNow = new Date().toISOString();

    const newMessage: ChatMessage = {
      id: Date.now().toString(),
      sender: role === 'student' ? "Tôi" : "Tôi (Host)",
      avatar: "https://i.pravatar.cc/150?u=me",
      content: content,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    const newQuestion: QuestionItem = {
      id: `q_${Date.now()}`,
      text: content.trim(),
      timestamp: isoNow,
    };

    setMessages((prev) => [...prev, newMessage]);

    // [GIỮ NGUYÊN — không xoá theo yêu cầu] cache cục bộ cũ, không còn ai
    // đọc lại (Dashboard giờ lấy dữ liệu chung từ server).
    const updatedQuestions = [...questions, newQuestion];
    setQuestions(updatedQuestions);
    localStorage.setItem("room_questions", JSON.stringify(updatedQuestions));

    // Gửi câu hỏi lên kho chung phía server, gắn đúng phiên học (?session=)
    aiFetch("/api/v1/questions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(newQuestion),
    }).catch((error) => console.error("Cannot submit question:", error));
  };

  const dashboardHref = sessionId
    ? `/dashboard/teacher?session=${encodeURIComponent(sessionId)}`
    : "/dashboard/teacher";

  if (role === null) return null;

  const centered = (text: string, color = '#94a3b8', withButton = false) => (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center', justifyContent: 'center', background: '#0b1120', color, padding: 24, textAlign: 'center' }}>
      <p>{text}</p>
      {withButton && (
        <button
          onClick={() => router.push('/sinhvien')}
          style={{ background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, padding: '10px 18px', fontWeight: 600, cursor: 'pointer' }}
        >
          Về trang chủ sinh viên
        </button>
      )}
    </div>
  );

  // ---------------- Giao diện SINH VIÊN (máy tính) ----------------
  if (role === 'student') {
    if (!sessionId) return centered('Hãy vào phòng học từ trang chủ sinh viên (nhập mã lớp).', '#94a3b8', true);
    if (student.loading) return centered('Đang vào lớp học...');
    if (student.error || !student.info) return centered(student.error || 'Không tìm thấy phiên học.', '#fca5a5', true);

    const info = student.info;
    const isLive = info.status === 'LIVE';
    const badge =
      info.status === 'LIVE' ? { text: 'Trực tiếp', color: '#10b981' }
      : info.status === 'SCHEDULED' ? { text: 'Phòng chờ', color: '#f59e0b' }
      : { text: info.status === 'ENDED' ? 'Đã kết thúc' : 'Đã hủy', color: '#64748b' };

    return (
      <div className={styles.container}>
        <QAToast />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0f172a', paddingRight: '20px', gap: 12 }}>
          <Header roomtitle={`${info.class.name} · ${info.title}`} thoigiantao={info.startedAt ?? roomInfo.createdAt} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span title="Tài khoản đang đăng nhập" style={{ fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 999, whiteSpace: 'nowrap', background: '#2563eb', color: '#fff' }}>Sinh viên: {userName || '—'}</span>
            <span style={{ fontSize: 12, color: '#94a3b8', whiteSpace: 'nowrap' }}>GV {info.lecturerName}</span>
            <span style={{ fontSize: 11, background: badge.color, color: '#fff', padding: '2px 10px', borderRadius: 12, fontWeight: 'bold' }}>
              {badge.text}
            </span>
          </div>
        </div>
        {!isLive && (
          <div style={{ background: '#422006', color: '#fcd34d', fontSize: 13, padding: '8px 16px', textAlign: 'center' }}>
            {info.status === 'SCHEDULED'
              ? 'Phòng chờ: giảng viên chưa bắt đầu buổi học. Trang sẽ tự cập nhật khi buổi học bắt đầu.'
              : 'Buổi học này không còn diễn ra.'}
          </div>
        )}
        <main className={styles.mainContent}>
          <SlideFollower />
          <Transcript enTrans={enTrans} vnTrans={vnTrans} />
          <Message message={messages} onSendMessage={handleSendMessage} />
        </main>
        <footer className={styles.controlesBtn}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 20px', background: '#0f172a', borderTop: '1px solid #1e293b' }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>
              Câu hỏi bạn gửi là ẩn danh và được gom nhóm cho giảng viên.
            </span>
          <div style={{ display: 'flex', gap: 10 }}>
            <Link
              href={sessionId ? `/summary?session=${encodeURIComponent(sessionId)}` : '/summary'}
              style={{ background: '#0f766e', color: '#fff', borderRadius: 8, padding: '8px 14px', fontWeight: 600, fontSize: 13, textDecoration: 'none' }}
            >
              Tóm tắt bài giảng
            </Link>
            <button
              onClick={() => router.push('/sinhvien')}
              style={{ background: '#dc2626', color: '#fff', border: 'none', borderRadius: 8, padding: '8px 18px', fontWeight: 600, cursor: 'pointer' }}
            >
              Rời lớp
            </button>
          </div>
          </div>
        </footer>
      </div>
    );
  }

  // ---------------- Giao diện GIẢNG VIÊN ----------------
  return (
    <div className={styles.container}>
      <QAToast />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0f172a', paddingRight: '20px', gap: 12 }}>
        <Header roomtitle={roomInfo.title} thoigiantao={roomInfo.createdAt} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span title="Tài khoản đang đăng nhập" style={{ fontSize: 11, fontWeight: 600, padding: '3px 10px', borderRadius: 999, whiteSpace: 'nowrap', background: '#7c3aed', color: '#fff' }}>Giảng viên: {userName || '—'}</span>
          <span style={{ fontSize: 12, color: sessionId ? '#38bdf8' : '#94a3b8', whiteSpace: 'nowrap' }}>
            {sessionId ? `Phiên: ${sessionId.slice(0, 8)}…` : 'Phòng chung (chưa gắn phiên)'}
          </span>
          <select
            value={speechLang}
            onChange={(e) => changeSpeechLang(e.target.value as SpeechLang)}
            aria-label="Ngôn ngữ nói"
            style={{ background: '#1e293b', color: '#e2e8f0', border: '1px solid #475569', borderRadius: 6, padding: '6px 8px', fontSize: 13 }}
          >
            <option value="auto">Tự nhận ngôn ngữ</option>
            <option value="vi">Tiếng Việt</option>
            <option value="en">English</option>
          </select>
          <Link
            href={sessionId ? `/giangvien/summary?session=${encodeURIComponent(sessionId)}` : "/giangvien/summary"}
            target="_blank"
            style={{
              background: '#0f766e',
              color: '#fff',
              padding: '8px 12px',
              borderRadius: '6px',
              textDecoration: 'none',
              fontSize: '13px',
              fontWeight: 600,
              whiteSpace: 'nowrap'
            }}
          >
            Tóm tắt & Heatmap ↗
          </Link>
          <Link
            href={dashboardHref}
            target="_blank"
            style={{
              background: '#2563eb',
              color: '#fff',
              padding: '8px 14px',
              borderRadius: '6px',
              textDecoration: 'none',
              fontSize: '13px',
              fontWeight: 600,
              whiteSpace: 'nowrap'
            }}
          >
            Mở Dashboard Giảng Viên ↗
          </Link>
        </div>
      </div>

      <UserParticipant users={users} />
      <main className={styles.mainContent}>
        <SlideViewer />
        <Transcript enTrans={enTrans} vnTrans={vnTrans} />
        <Message message={messages} onSendMessage={handleSendMessage} />
      </main>
      <footer className={styles.controlesBtn}>
        <BottomControles
          nguoiThamGia={users.length}
          onMic={handleMicToggle}
          onMutedAll={() => stopRecording()}
          onInvited={() => {
            if (typeof window !== 'undefined') {
              void navigator.clipboard?.writeText(window.location.href);
              alert('Đã sao chép liên kết phòng học vào bộ nhớ tạm!');
            }
          }}
          onCam={() =>
            alert('Phòng AI tối ưu băng thông cho Phụ đề giọng nói & Slide PDF (không phát luồng video camera).')
          }
          onEndCall={() => {
            stopRecording();
            router.push(
              sessionId
                ? `/giangvien/classroom/${encodeURIComponent(sessionId)}`
                : '/giangvien/classroom',
            );
          }}
        />
      </footer>
    </div>
  );
}
