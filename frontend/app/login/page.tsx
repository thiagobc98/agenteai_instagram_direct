"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "../../lib/api";
import { IconChats, IconLock, IconUser } from "../../components/icons";
import styles from "./page.module.css";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.login(username, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Falha ao conectar com a API");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={styles.page}>
      <form onSubmit={handleSubmit} className={`card ${styles.card}`}>
        <div className={styles.logo}>
          <span className={styles.logoMark}>
            <IconChats size={20} />
          </span>
          <div>
            <h1 className={styles.title}>Patricia Berberich</h1>
            <p className={styles.subtitle}>Painel administrativo</p>
          </div>
        </div>

        <label className={styles.field}>
          <span className={styles.label}>Usuário</span>
          <div className={styles.inputWrap}>
            <span className={styles.inputIcon}>
              <IconUser size={16} />
            </span>
            <input
              className={styles.input}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </div>
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Senha</span>
          <div className={styles.inputWrap}>
            <span className={styles.inputIcon}>
              <IconLock size={16} />
            </span>
            <input
              className={styles.input}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
        </label>

        {error && <span className={styles.error}>{error}</span>}

        <button type="submit" disabled={loading} className={styles.submit}>
          {loading ? "Entrando..." : "Entrar"}
        </button>
      </form>
    </main>
  );
}
