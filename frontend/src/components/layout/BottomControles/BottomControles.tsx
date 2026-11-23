"use client";
import React,{useState} from "react";
import styles from './BottomControles.module.css'
import { Mic, MicOff, UserPlus, PhoneOff, CameraOff, Camera } from 'lucide-react';
interface BottomControlesProps{
    nguoiThamGia?: number;
    // Trả về false (hoặc Promise<false>) nếu không bật được micro -> nút tự quay lại trạng thái tắt
    onMic?:(isMicMuted: boolean) => void | boolean | Promise<void | boolean>;
    onCam?:(isCamOff: boolean) => void;
    onMutedAll?:() => void;
    onCamOffAll?: () => void;
    onInvited?:() =>void;
    onEndCall?:() => void;
}
export default function BottomControles({nguoiThamGia = 0, onMic,onCam,onCamOffAll,onEndCall,onInvited,onMutedAll}:BottomControlesProps){
    // Bắt đầu ở trạng thái TẮT: trang chưa ghi âm gì cho tới khi người dùng bấm bật micro
    const [isMicOn,setIsMicOn] = useState(false);
    const [isCamOn,setIsCamOn] = useState(false);
    const onToggleMic = async () => {
        const nextState = !isMicOn;
        setIsMicOn(nextState);
        if(onMic){
            const ok = await onMic(!nextState);
            if(ok === false) setIsMicOn(!nextState); // không bật được micro (bị chặn quyền...)
        }
    };
    const onToggleCam = () => {
        const nextState = !isCamOn;
        setIsCamOn(nextState);
        if(onCam){
            onCam(!nextState);
        }
    };
    return(
        <footer className={styles.container}>
            <div className={styles.leftBtn}>
                <button onClick={onMutedAll} className={styles.onMutedAllBtn} title="Tat mic toan bo">
                    <MicOff className={styles.micOffLucide}/>Mute All
                </button>
                <button onClick={onCamOffAll} className={styles.onCamOffAllBtn} title="Tat cam toan bo">
                    <CameraOff className={styles.cameraOffLucide}/>Stop All Cameras
                </button>
            </div>
            <div className={styles.middleBtn}>
                <button className={styles.Particiants}>
                    Particiants {nguoiThamGia > 0 && `${nguoiThamGia}`}
                </button>
                <button onClick={onInvited} className={styles.inviteBtn} title="Moi nguoi khac tham gia">
                    <UserPlus className={styles.userPlusLucide}/>Invite
                </button>
            </div>
            <div className={styles.rightBtn}>
                <button 
                onClick={onToggleMic} 
                className={`${styles.onToggleMicBtn} ${isMicOn ? styles.micOnBtn : styles.micOffBtn}`} 
                title={isMicOn ? "Tat mic":"Bat mic"}>
                    {isMicOn ? <Mic className={styles.micLucide}/>:<MicOff className={styles.micOffLucide}/>}Mic
                </button>
                <button
                onClick={onToggleCam}
                className={`${styles.onToggleCamBtn} ${isCamOn ? styles.isCamOnBtn : styles.isCamOffBtn}`}
                title={isCamOn ? "Tat cam":"Bat cam"}>
                    {isCamOn ? <Camera className={styles.micLucide}/>:<CameraOff className={styles.cameraOffLucide}/>}Cam
                </button>
                <button onClick={onEndCall} className={styles.onEndCallBtn} title="End Call">
                    <PhoneOff className={styles.phoneOffLucide}/>End
                </button>
            </div>
        </footer>
    );
}
