"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type AdminUser } from "../../lib/api";
import AppShell from "../../components/AppShell";

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AdminUser | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => router.replace("/login"))
      .finally(() => setChecked(true));
  }, [router]);

  async function handleLogout() {
    await api.logout().catch(() => {});
    router.push("/login");
  }

  if (!checked) {
    return (
      <main style={{ padding: "2rem" }}>
        <p className="muted">Carregando...</p>
      </main>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <AppShell user={user} onLogout={handleLogout}>
      {children}
    </AppShell>
  );
}
