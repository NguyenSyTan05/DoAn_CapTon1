"use client";
import Image from 'next/image';
import {useEffect,useState} from 'react';
import styles from './Header.module.css';

interface HeaderProps {
    roomtitle?: string;
    thoigiantao?: string | number | Date;
}
export default function Header({roomtitle, thoigiantao}: HeaderProps) {  
    const [currentTime, setCurrentTime] = useState("00:00:00");
    useEffect(()=>{
        if(!thoigiantao) return;
        const updateTime = () => {
        const startTime = new Date(thoigiantao).getTime();
        const totalSeconds = new Date().getTime() - startTime;
        const hours = Math.floor(totalSeconds / 3600000);
        const minutes = Math.floor((totalSeconds % 3600000) / 60000);
        const seconds = Math.floor((totalSeconds % 60000) / 1000);
        setCurrentTime(`${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`);
        };
        updateTime();
        const interval = setInterval(updateTime, 1000);
        return () => clearInterval(interval);
    }, [thoigiantao]);
    return(
        <header className={styles.header}>
            <div className={styles.leftHeader}>
                <div className={styles.logo}>
                    <Image
                        src="/Logo.png"
                        alt="ClassBridge Logo"
                        width={40}
                        height={40}
                        priority
                        className={styles.logoImg}
                    />
                </div>
                <div className={styles.title}>
                    <p>ClassBridge</p>
                    <span>AI Classroom</span>
                </div>
            </div>
            <div className={styles.leftHeader}>
                <div className={styles.title}>{roomtitle}</div>
                <div className={styles.time}>{currentTime}</div>
            </div>
        </header>
    );
}
