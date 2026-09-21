"use client";

import { useEffect, useState } from "react";
import { api, type Metrics } from "../../../lib/api";
import StatCard from "../../../components/StatCard";
import { CardsSkeleton } from "../../../components/LoadingState";
import { IconAlertCircle, IconChats, IconClock, IconInbox } from "../../../components/icons";
import styles from "./page.module.css";

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.metrics().then(setMetrics).catch((e) => setError(e.message));
    const interval = setInterval(() => {
      api.metrics().then(setMetrics).catch(() => {});
    }, 10_000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ padding: "1.6rem 2rem" }}>
      <div className={styles.header}>
        <h1 className={styles.title}>Dashboard</h1>
        <p className="muted">Atualizado automaticamente a cada 10s</p>
      </div>

      {error && <p className="error-text">{error}</p>}
      {!metrics && !error && <CardsSkeleton />}

      {metrics && (
        <div className={styles.grid}>
          <StatCard
            label="Mensagens hoje"
            value={metrics.total_today}
            icon={<IconChats size={20} />}
          />
          <StatCard
            label="Falhas hoje"
            value={metrics.failures_today}
            icon={<IconAlertCircle size={20} />}
            tone={metrics.failures_today > 0 ? "danger" : "neutral"}
          />
          <StatCard
            label="Tempo médio (s)"
            value={metrics.avg_processing_time_seconds ?? "-"}
            icon={<IconClock size={20} />}
          />
          <StatCard
            label="Fila atual"
            value={metrics.queue_size}
            icon={<IconInbox size={20} />}
          />
        </div>
      )}
    </div>
  );
}
