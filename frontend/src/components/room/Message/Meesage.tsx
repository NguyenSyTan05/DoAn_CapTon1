"use client";
import { aiWsUrl } from '../../../lib/ai';
import React, { FormEvent, useEffect, useState } from 'react';
import styles from './Meesage.module.css';
import { Send, MessageSquare, HelpCircle, BarChart2 } from "lucide-react";
import{ChatMessage} from '../../../types';

interface AnswerOutput {
    representative_id: string;
    representative_text: string;
    total_count: number;
    answer_text: string;
    answered_at: string;
}

interface MessageProps {
    message?: ChatMessage[];
    onSendMessage?: (content: string) => void;
}
export default function Message({message = [], onSendMessage}: MessageProps) {
    const [inputValue, setInputValue] = useState('');
    const [activeTab, setActiveTab] = useState<'Chat' | 'Q&A' | 'Poll'>('Chat');

    // [CUSTOM] Q&A tab — CHỈ XEM, không có ô nhập (ô nhập câu trả lời nằm
    // ở Dashboard Giảng viên). Dùng chung /api/v1/ws/qa với QAToast/
    // student page — nhận "snapshot" lúc kết nối rồi "upsert"/"remove"
    // real-time khi giảng viên thao tác trên Dashboard.
    const [answers, setAnswers] = useState<AnswerOutput[]>([]);

    useEffect(() => {
        const wsUrl = aiWsUrl("/api/v1/ws/qa");
        const ws = new WebSocket(wsUrl);

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'snapshot') {
                    setAnswers(msg.answers ?? []);
                } else if (msg.type === 'upsert') {
                    setAnswers((prev) => {
                        const next = prev.filter((a) => a.representative_id !== msg.answer.representative_id);
                        next.push(msg.answer);
                        next.sort((a, b) => b.total_count - a.total_count || a.answered_at.localeCompare(b.answered_at));
                        return next;
                    });
                } else if (msg.type === 'remove') {
                    setAnswers((prev) => prev.filter((a) => a.representative_id !== msg.representative_id));
                }
            } catch (err) {
                console.warn('Q&A WebSocket parse error:', err);
            }
        };

        return () => ws.close();
    }, []);

    const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const content = inputValue.trim();
        if (!content || !onSendMessage) return;

        onSendMessage(content);
        setInputValue('');
    };

    return(
        <div className={styles.sidebar}>
            <div className={styles.sideHeader}>
                <button className={activeTab === 'Chat' ? styles.active : ''} onClick={() => setActiveTab('Chat')}>
                    <MessageSquare className={styles.icon} size={20} color="#000"/> Chat
                </button>
                <button className={activeTab === 'Q&A' ? styles.active : ''} onClick={() => setActiveTab('Q&A')}>
                    <HelpCircle className={styles.icon} size={20} color="#000"/> Q&A
                </button>
                <button className={activeTab === 'Poll' ? styles.active : ''} onClick={() => setActiveTab('Poll')}>
                    <BarChart2 className={styles.icon} size={20} color="#000"/> Poll
                </button>
            </div>
            <div className={styles.messageArea}>
                {activeTab === 'Chat' && (message.length > 0 ? message.map((item) => (
                    <article key={item.id} className={styles.message}>
                        <div className={styles.messageMeta}>
                            <span>{item.sender}</span>
                            <time>{item.timestamp}</time>
                        </div>
                        <p>{item.content}</p>
                    </article>
                )) : <p className={styles.emptyState}>No messages yet.</p>)}

                {activeTab === 'Q&A' && (answers.length > 0 ? answers.map((a) => (
                    <article key={a.representative_id} className={styles.message}>
                        <div className={styles.messageMeta}>
                            <span>{a.total_count} student{a.total_count > 1 ? 's' : ''} asked</span>
                        </div>
                        <p>{a.representative_text}</p>
                        <p style={{ color: '#6ee7b7', marginTop: '4px' }}>{a.answer_text}</p>
                    </article>
                )) : <p className={styles.emptyState}>No answers yet.</p>)}

                {activeTab === 'Poll' && <p className={styles.emptyState}>Nothing here yet.</p>}
            </div>
      <form className={styles.inputArea} onSubmit={handleSubmit}>
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder="Type a message..."
          className={styles.inputField}
        />
            <button className={styles.sendBtn} type="submit" aria-label="Send message" disabled={!inputValue.trim()}>
                <Send className="w-4 h-4" />
            </button>
        </form>
    </div>
    );
}
