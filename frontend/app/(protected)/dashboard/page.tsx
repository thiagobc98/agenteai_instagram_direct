"use client";

import { useEffect, useState } from "react";
import { api, type CalendarEvent, type Metrics } from "../../../lib/api";
import StatCard from "../../../components/StatCard";
import AppointmentCard from "../../../components/AppointmentCard";
import { CardsSkeleton } from "../../../components/LoadingState";
import { IconAlertCircle, IconChats, IconClock, IconInbox } from "../../../components/icons";
import styles from "./page.module.css";

const UPCOMING_DAYS_AHEAD = 30;
const UPCOMING_LIMIT = 8;

function startOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

function addDays(date: Date, days: number): Date {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d;
}

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [todayEvents, setTodayEvents] = useState<CalendarEvent[] | null>(null);
  const [todayError, setTodayError] = useState<string | null>(null);
  const [upcomingEvents, setUpcomingEvents] = useState<CalendarEvent[] | null>(null);
  const [upcomingError, setUpcomingError] = useState<string | null>(null);

  useEffect(() => {
    api.metrics().then(setMetrics).catch((e) => setError(e.message));
    const interval = setInterval(() => {
      api.metrics().then(setMetrics).catch(() => {});
    }, 10_000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const now = new Date();
    const todayStart = startOfDay(now);
    const todayEnd = addDays(todayStart, 1);

    function load() {
      api
        .calendarEvents(todayStart, todayEnd)
        .then((data) => setTodayEvents(data.enabled ? data.events : []))
        .catch((e) => setTodayError(e.message));

      api
        .calendarEvents(todayEnd, addDays(todayEnd, UPCOMING_DAYS_AHEAD))
        .then((data) =>
          setUpcomingEvents(data.enabled ? data.events.slice(0, UPCOMING_LIMIT) : []),
        )
        .catch((e) => setUpcomingError(e.message));
    }

    load();
    const interval = setInterval(load, 60_000);
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

      <div className={styles.appointments}>
        <AppointmentCard
          title="Consultas de hoje"
          events={todayEvents}
          error={todayError}
          emptyText="Nenhuma consulta hoje"
        />
        <AppointmentCard
          title="Próximas consultas"
          events={upcomingEvents}
          error={upcomingError}
          emptyText="Nenhuma consulta agendada"
          groupByDay
        />
      </div>
    </div>
  );
}
