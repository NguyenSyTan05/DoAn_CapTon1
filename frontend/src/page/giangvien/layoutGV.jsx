"use client";

import { useState } from "react";
import Layout from "../../components/shell/layout";
import authService from "../../services/auth.service";
import LecturerSidebar from "./sidebar";
import styles from "./layoutGV.module.css";

export default function LecturerLayout({ user = null, children }) {
  const [storedUser] = useState(() => {
    if (user) return user;
    try {
      return authService.getCurrentUser();
    } catch {
      return null;
    }
  });

  return (
    <Layout user={user || storedUser}>
      <div className={styles.shell}>
        <LecturerSidebar />
        <main className={styles.content}>{children}</main>
      </div>
    </Layout>
  );
}
