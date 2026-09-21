import type { CalendarEvent } from "../lib/api";
import { formatTime } from "../lib/format";
import { IconCalendar } from "./icons";
import styles from "./AppointmentCard.module.css";

function dayLabel(date: Date): string {
  const label = date.toLocaleDateString("pt-BR", {
    weekday: "short",
    day: "2-digit",
    month: "short",
  });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export default function AppointmentCard({
  title,
  events,
  error,
  emptyText,
  groupByDay = false,
}: {
  title: string;
  events: CalendarEvent[] | null;
  error?: string | null;
  emptyText: string;
  groupByDay?: boolean;
}) {
  let lastDayKey = "";

  return (
    <div className={`card ${styles.card}`}>
      <p className={styles.title}>{title}</p>

      {error && <p className="error-text">{error}</p>}

      {!events && !error && (
        <div className={styles.skeleton}>
          {[1, 2, 3].map((i) => (
            <div key={i} className={styles.skeletonRow} />
          ))}
        </div>
      )}

      {events && events.length === 0 && !error && (
        <div className={styles.empty}>
          <IconCalendar size={18} />
          <span>{emptyText}</span>
        </div>
      )}

      {events && events.length > 0 && (
        <ul className={styles.list}>
          {events.map((event) => {
            const start = new Date(event.start);
            const dayKey = start.toDateString();
            const showDayHeader = groupByDay && dayKey !== lastDayKey;
            lastDayKey = dayKey;

            return (
              <li key={event.id}>
                {showDayHeader && <p className={styles.dayHeader}>{dayLabel(start)}</p>}
                <div className={styles.row}>
                  <span className={styles.time}>{formatTime(event.start)}</span>
                  <div className={styles.info}>
                    <p className={styles.summary}>{event.patient_name || event.summary}</p>
                    {event.patient_name && event.summary && (
                      <p className={styles.sub}>{event.summary}</p>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
