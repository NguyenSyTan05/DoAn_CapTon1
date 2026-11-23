"use client";
import React, { useState } from 'react';
import Image from 'next/image';
import { MicOff, VideoOff, MoreVertical, UserMinus } from 'lucide-react';
import { User } from '../../../types';
import styles from './UserParticipant.module.css';

interface userProps {
  users?: User[];
}

export default function UserParticipant({ users = [] }: userProps) {
  const [activeMenu, setActiveMenu] = useState<string | null>(null);

  return (
    <div className={styles.userHeader}>
      <div className={styles.leftuserHeader}>
        <span className={styles.classRoom}>Classroom</span>
        <span className={styles.usersName}>{users.length}</span>
      </div>

      <div className={styles.camUser}>
        {users.map((user) => (
          <div key={user.id} className={styles.cameraOff}>
            {user.isCameraOff ? (
              <div className={styles.camUser}>
                <div className={styles.cam}>
                  {user.name.charAt(0)}
                </div>
              </div>
            ) : (
              <Image src={user.avatar} alt={user.name} width={128} height={80} className={styles.avatarUser} />
            )}
            
            <div className={styles.micUser}>
              <span className={styles.micOff}>{user.name}</span>
              <div className={styles.mic}>
                {user.isMicOff && <MicOff />}
              </div>
            </div>

            <button 
              onClick={() => setActiveMenu(activeMenu === user.id ? null : user.id)}
              className={styles.btnUser}
            >
              <MoreVertical className={styles.iconVertical} />
            </button>

            {activeMenu === user.id && (
              <div className={styles.btnBox}>
                <button className={styles.btnMic}>
                  <MicOff className={styles.micMute} /> Mute Mic
                </button>
                <button className={styles.btnCam}>
                  <VideoOff className={styles.camOff} /> Turn Off Camera
                </button>
                <button className={styles.btnRemove}>
                  <UserMinus className={styles.remove} /> Remove from Class
                </button>
              </div>
            )}
          </div>
        ))}
      </div>

      {users.length > 0 && (
        <div className={styles.rightUserHeader}>
          <button className={styles.btnMore}>
            More
          </button>
          <button className={styles.btnViewAll}>
            View All
          </button>
        </div>
      )}
    </div>
  );
}
