import type { ReactNode } from "react";
import styles from "./KpiCard.module.css";

export type KpiTone = "brand" | "gold" | "blue" | "danger";

// Cartão de indicador: valor grande, ícone colorido, texto de apoio e —
// opcionalmente — a variação contra o período anterior (ex.: hoje vs ontem).
export default function KpiCard({
  label,
  value,
  icon,
  hint,
  delta,
  deltaLabel = "vs ontem",
  tone = "brand",
}: {
  label: string;
  value: ReactNode;
  icon: ReactNode;
  hint?: ReactNode;
  delta?: number | null;
  deltaLabel?: string;
  tone?: KpiTone;
}) {
  const deltaClass =
    delta == null || delta === 0 ? styles.flat : delta > 0 ? styles.up : styles.down;

  return (
    <div className={`card ${styles.card}`}>
      <div className={`${styles.iconWrap} ${styles[tone]}`}>{icon}</div>
      <div className={styles.body}>
        <p className={styles.label}>{label}</p>
        <p className={styles.value}>{value}</p>
        <p className={styles.foot}>
          {delta != null && (
            <span className={`${styles.delta} ${deltaClass}`}>
              {delta > 0 ? "▲ +" : delta < 0 ? "▼ " : "= "}
              {delta === 0 ? "igual" : delta} {deltaLabel}
            </span>
          )}
          {hint && <span className={styles.hint}>{hint}</span>}
        </p>
      </div>
    </div>
  );
}
