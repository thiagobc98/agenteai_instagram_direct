"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { AdminUser } from "../lib/api";
import Avatar from "./Avatar";
import {
  IconAgents,
  IconCalendar,
  IconChats,
  IconDashboard,
  IconLogout,
  IconMenu,
  IconX,
} from "./icons";
import styles from "./AppShell.module.css";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: IconDashboard },
  { href: "/chats", label: "Conversas", icon: IconChats },
  { href: "/agenda", label: "Agenda", icon: IconCalendar },
  { href: "/agents", label: "Agentes", icon: IconAgents },
];

export default function AppShell({
  user,
  onLogout,
  children,
}: {
  user: AdminUser;
  onLogout: () => void;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  const nav = (
    <nav className={styles.nav}>
      {NAV_ITEMS.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`${styles.navItem} ${active ? styles.navItemActive : ""}`}
            title={item.label}
            onClick={() => setMobileOpen(false)}
          >
            <Icon size={19} />
            <span className={styles.navLabel}>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <button
          className={styles.hamburger}
          onClick={() => setMobileOpen(true)}
          aria-label="Abrir menu"
        >
          <IconMenu size={20} />
        </button>
        <div className={styles.brand}>
          <span className={styles.brandMark}>I</span>
          <span>Instagram CRM</span>
        </div>
        <div className={styles.topbarUser}>
          <Avatar seed={user.username} size={30} />
        </div>
      </header>

      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>I</span>
          <span className={styles.navLabel}>Instagram CRM</span>
        </div>

        {nav}

        <div className={styles.sidebarFooter}>
          <Avatar seed={user.username} size={34} />
          <div className={styles.navLabel}>
            <p className={styles.userName}>{user.username}</p>
            <p className={styles.userRole}>Administrador</p>
          </div>
          <button className={styles.logoutButton} onClick={onLogout} title="Sair">
            <IconLogout size={17} />
          </button>
        </div>
      </aside>

      {mobileOpen && (
        <div className={styles.overlay} onClick={() => setMobileOpen(false)}>
          <div className={styles.drawer} onClick={(e) => e.stopPropagation()}>
            <div className={styles.drawerHeader}>
              <div className={styles.brand}>
                <span className={styles.brandMark}>I</span>
                <span>Instagram CRM</span>
              </div>
              <button
                className={styles.iconButton}
                onClick={() => setMobileOpen(false)}
                aria-label="Fechar menu"
              >
                <IconX size={18} />
              </button>
            </div>
            {nav}
            <div className={styles.sidebarFooter}>
              <Avatar seed={user.username} size={34} />
              <div>
                <p className={styles.userName}>{user.username}</p>
                <p className={styles.userRole}>Administrador</p>
              </div>
              <button className={styles.logoutButton} onClick={onLogout} title="Sair">
                <IconLogout size={17} />
              </button>
            </div>
          </div>
        </div>
      )}

      <main className={styles.main}>{children}</main>
    </div>
  );
}
