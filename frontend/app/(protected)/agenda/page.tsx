"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type CalendarEvent } from "../../../lib/api";
import EmptyState from "../../../components/EmptyState";
import { IconCalendar, IconChevronLeft, IconChevronRight } from "../../../components/icons";
import { formatTime } from "../../../lib/format";
import styles from "./page.module.css";

const DEFAULT_HOUR_START = 7;
const DEFAULT_HOUR_END = 20;
const ROW_HEIGHT = 48;
const MIN_EVENT_HEIGHT = 22;

function startOfWeek(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - d.getDay());
  return d;
}

function addDays(date: Date, days: number): Date {
  const d = new Date(date);
  d.setDate(d.getDate() + days);
  return d;
}

function hoursFromMidnight(date: Date): number {
  return date.getHours() + date.getMinutes() / 60;
}

function isSameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

function monthLabel(date: Date): string {
  const label = date.toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export default function AgendaPage() {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()));
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [calendarId, setCalendarId] = useState<string | null>(null);
  const [hourRange, setHourRange] = useState({ start: DEFAULT_HOUR_START, end: DEFAULT_HOUR_END });
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const weekEnd = useMemo(() => addDays(weekStart, 7), [weekStart]);
  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  );
  const today = useMemo(() => new Date(), []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .calendarEvents(weekStart, weekEnd)
      .then((data) => {
        if (cancelled) return;
        setEnabled(data.enabled);
        setCalendarId(data.calendar_id ?? null);
        setEvents(data.events);
        if (data.business_hour_start != null && data.business_hour_end != null) {
          setHourRange({
            start: Math.min(DEFAULT_HOUR_START, data.business_hour_start),
            end: Math.max(DEFAULT_HOUR_END, data.business_hour_end + 1),
          });
        }
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [weekStart, weekEnd]);

  const hours = useMemo(
    () => Array.from({ length: hourRange.end - hourRange.start }, (_, i) => hourRange.start + i),
    [hourRange],
  );
  const trackHeight = hours.length * ROW_HEIGHT;

  const eventsByDay = useMemo(() => {
    const map = new Map<number, { event: CalendarEvent; start: Date; end: Date }[]>();
    for (const event of events) {
      if (event.all_day) continue;
      const start = new Date(event.start);
      const end = new Date(event.end);
      const dayIndex = days.findIndex((d) => isSameDay(d, start));
      if (dayIndex === -1) continue;
      if (!map.has(dayIndex)) map.set(dayIndex, []);
      map.get(dayIndex)!.push({ event, start, end });
    }
    return map;
  }, [events, days]);

  const allDayEvents = useMemo(() => events.filter((e) => e.all_day), [events]);

  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <div className={styles.titleRow}>
          <IconCalendar size={22} />
          <h1 className={styles.title}>Agenda</h1>
        </div>

        <div className={styles.toolbar}>
          <button className={styles.todayButton} onClick={() => setWeekStart(startOfWeek(new Date()))}>
            Hoje
          </button>
          <div className={styles.nav}>
            <button
              className={styles.iconButton}
              aria-label="Semana anterior"
              onClick={() => setWeekStart((w) => addDays(w, -7))}
            >
              <IconChevronLeft size={18} />
            </button>
            <button
              className={styles.iconButton}
              aria-label="Próxima semana"
              onClick={() => setWeekStart((w) => addDays(w, 7))}
            >
              <IconChevronRight size={18} />
            </button>
          </div>
          <span className={styles.monthLabel}>{monthLabel(weekStart)}</span>
          {enabled && calendarId && <span className={styles.connected}>Conectado · {calendarId}</span>}
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}

      {loaded && !enabled && !error && (
        <EmptyState
          icon={<IconCalendar size={26} />}
          title="Google Calendar não conectado"
          description="Configure GOOGLE_CALENDAR_ENABLED e as credenciais da service account no backend para ver a agenda aqui."
        />
      )}

      {enabled && (
        <div className={styles.calendar}>
          <div className={styles.dayHeaderRow}>
            <div className={styles.gutterHeader} />
            {days.map((day) => (
              <div
                key={day.toISOString()}
                className={`${styles.dayHeader} ${isSameDay(day, today) ? styles.dayHeaderToday : ""}`}
              >
                <span className={styles.dayName}>
                  {day.toLocaleDateString("pt-BR", { weekday: "short" }).toUpperCase()}
                </span>
                <span className={styles.dayNumber}>{day.getDate()}</span>
              </div>
            ))}
          </div>

          {allDayEvents.length > 0 && (
            <div className={styles.allDayRow}>
              <div className={styles.gutterHeader} />
              {days.map((day) => (
                <div key={day.toISOString()} className={styles.allDayCell}>
                  {allDayEvents
                    .filter((e) => isSameDay(new Date(e.start), day))
                    .map((e) => (
                      <span key={e.id} className={styles.allDayChip} title={e.summary}>
                        {e.summary}
                      </span>
                    ))}
                </div>
              ))}
            </div>
          )}

          <div className={styles.body}>
            <div className={styles.gutter} style={{ height: trackHeight }}>
              {hours.map((h) => (
                <div key={h} className={styles.hourLabel} style={{ height: ROW_HEIGHT }}>
                  {h === 0 ? "" : `${h % 24}h`}
                </div>
              ))}
            </div>

            {days.map((day, dayIndex) => (
              <div
                key={day.toISOString()}
                className={`${styles.dayTrack} ${isSameDay(day, today) ? styles.dayTrackToday : ""}`}
                style={{
                  height: trackHeight,
                  backgroundSize: `100% ${ROW_HEIGHT}px`,
                }}
              >
                {(eventsByDay.get(dayIndex) ?? []).map(({ event, start, end }) => {
                  const top = (hoursFromMidnight(start) - hourRange.start) * ROW_HEIGHT;
                  const height = Math.max(
                    (hoursFromMidnight(end) - hoursFromMidnight(start)) * ROW_HEIGHT,
                    MIN_EVENT_HEIGHT,
                  );
                  return (
                    <div
                      key={event.id}
                      className={styles.event}
                      style={{ top, height }}
                      title={`${event.summary} · ${formatTime(event.start)} – ${formatTime(event.end)}`}
                    >
                      <span className={styles.eventTitle}>{event.summary}</span>
                      <span className={styles.eventTime}>
                        {formatTime(event.start)} – {formatTime(event.end)}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
