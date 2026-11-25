"use client";

import { useState } from "react";
import { NavLink, useNavigate } from "@/lib/router-compat";
import {
  LuActivity,
  LuBookOpen,
  LuChevronLeft,
  LuClipboardList,
  LuLayoutDashboard,
  LuMenu,
  LuUsersRound,
} from "react-icons/lu";
import styles from "./dashboard.module.css";

const NAV_ITEMS = [
  { label: "Dashboard", href: "/admin", icon: LuLayoutDashboard, end: true },
  {
    label: "Quản lý người dùng",
    href: "/admin/users",
    icon: LuUsersRound,
  },
  { label: "Ghi log", href: "/admin/logs", icon: LuClipboardList },
  {
    label: "Mức độ tương tác",
    href: "/admin/engagement",
    icon: LuActivity,
  },
  {
    label: "Quản lý danh sách lớp",
    href: "/admin/classes",
    icon: LuBookOpen,
  },
];

export default function AdminSidebar() {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const navigate = useNavigate();

  return (
    <aside
      className={`${styles.sidebar} ${
        isCollapsed ? styles.sidebarCollapsed : ""
      }`}
    >
      <div className={styles.sidebarHeaderToggle}>
        {!isCollapsed && (
          <button
            type="button"
            className={styles.sidebarBrandButton}
            onClick={() => navigate("/")}
            aria-label="Về trang chủ"
            title="Về trang chủ"
          >
            <span className={styles.sidebarBrand}>ClassBridge</span>
          </button>
        )}
        <button
          type="button"
          className={styles.sidebarCollapseToggle}
          aria-label={isCollapsed ? "Mở rộng menu" : "Thu gọn menu"}
          aria-expanded={!isCollapsed}
          onClick={() => setIsCollapsed((collapsed) => !collapsed)}
        >
          {isCollapsed ? (
            <LuMenu size={20} aria-hidden="true" />
          ) : (
            <LuChevronLeft size={20} aria-hidden="true" />
          )}
        </button>
      </div>
      <nav className={styles.navMenu} aria-label="Menu quản trị">
        {NAV_ITEMS.map(({ label, href, icon: Icon, end }) => (
          <NavLink
            key={href}
            to={href}
            end={end}
            className={({ isActive }) =>
              `${styles.navItem} ${isActive ? styles.navItemActive : ""}`
            }
            title={isCollapsed ? label : undefined}
          >
            <Icon size={18} aria-hidden="true" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  );
}