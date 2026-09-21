import { formatNumber } from "../../lib/format";
import styles from "./charts.module.css";

// Ranking em barras horizontais (ex.: assuntos mais perguntados).
export default function HBarList({
  items,
  color = "var(--chart-1)",
}: {
  items: { label: string; value: number }[];
  color?: string;
}) {
  const max = Math.max(...items.map((i) => i.value), 1);

  return (
    <ul className={styles.rank}>
      {items.map((item) => (
        <li key={item.label} className={styles.rankRow}>
          <div className={styles.rankHead}>
            <span>{item.label}</span>
            <strong>{formatNumber(item.value)}</strong>
          </div>
          <div className={styles.rankTrack}>
            <div
              className={styles.rankFill}
              style={{ width: `${(item.value / max) * 100}%`, background: color }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}
