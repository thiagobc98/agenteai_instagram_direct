"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { AdminUser } from "../lib/api";
import Avatar from "./Avatar";
import {
  IconAgents,
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
  { href: "/agents", label: "Agentes", icon: IconAgents },
];

function Brand() {
  return (
    <div className={styles.brand}>
      <Image
        src="/logo-loja.jpg"
        alt="Logo Patricia Berberich"
        width={38}
        height={38}
        unoptimized
        className={styles.brandLogo}
      />
      <div className={styles.navLabel}>
        <p className={styles.brandName}>Central Berberich</p>
        <p className={styles.brandSub}>Atendimento Instagram</p>
      </div>
    </div>
  );
}

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
        <Brand />
        <div className={styles.topbarUser}>
          <Avatar seed={user.username} size={30} />
        </div>
      </header>

      <aside className={styles.sidebar}>
        <Brand />

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
              <Brand />
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
