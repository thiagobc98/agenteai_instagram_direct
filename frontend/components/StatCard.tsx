import type { ReactNode } from "react";
import styles from "./StatCard.module.css";

export default function StatCard({
  label,
  value,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: number | string;
  icon: ReactNode;
  tone?: "neutral" | "danger";
}) {
  return (
    <div className={`card ${styles.card}`}>
      <div className={`${styles.iconWrap} ${tone === "danger" ? styles.danger : ""}`}>
        {icon}
      </div>
      <div>
        <p className={styles.label}>{label}</p>
        <p className={styles.value}>{value}</p>
      </div>
    </div>
  );
}
