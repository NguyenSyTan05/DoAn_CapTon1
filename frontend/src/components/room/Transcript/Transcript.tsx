"use client";
import React from 'react';
import styles from './Transcript.module.css';  
import { Languages, Globe } from 'lucide-react';
import type { TranScript } from '../../../types';

interface LiveTranScriptProps {
  enTrans?: TranScript[];
  vnTrans?: TranScript[];
}

export default function Transcript({ enTrans = [], vnTrans = [] }: LiveTranScriptProps) {
  return (
    <div className={styles.transScriptBox}>
      <div className={styles.tranScriptContainerEN}>
        <div className={styles.tranScriptEN}>
          <span className={styles.EN}>
            <Globe className="w-3.5 h-3.5" /> EN (English)
          </span>
        </div>
        <div className={styles.scrollbar}>
          {enTrans.map((sub) => (
            <p key={sub.id} className={styles.subId}>
              <span className={styles.subtTimeStamp}>[{sub.timestamp}]</span>
              <strong className={styles.subSpeaker}>{sub.speaker}:</strong>
              <span>{sub.text}</span>
            </p>
          ))}
        </div>
      </div>

      <div className={styles.transScriptContainerVN}>
        <div className={styles.tranScriptVN}>
          <span className={styles.EN}>
            <Languages className="w-3.5 h-3.5" /> VN (VietNam)
          </span>
        </div>
        <div className={styles.scrollbar}>
          {vnTrans.map((sub) => (
            <p key={sub.id} className={styles.subId}>
              <span className={styles.subtTimeStamp}>[{sub.timestamp}]</span>
              <strong className={styles.subSpeaker}>{sub.speaker}:</strong>
              <span>{sub.text}</span>
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}