import type { ReactNode } from "react";
import styles from "./charts.module.css";

// Moldura padrão dos gráficos: título, legenda/subtítulo e estado vazio.
export default function ChartCard({
  title,
  subtitle,
  legend,
  empty = false,
  span = 1,
  children,
}: {
  title: string;
  subtitle?: string;
  legend?: ReactNode;
  empty?: boolean;
  span?: 1 | 2;
  children: ReactNode;
}) {
  return (
    <section className={`card ${styles.card} ${span === 2 ? styles.span2 : ""}`}>
      <header className={styles.cardHead}>
        <div>
          <h2 className={styles.cardTitle}>{title}</h2>
          {subtitle && <p className={styles.cardSub}>{subtitle}</p>}
        </div>
        {legend}
      </header>
      {empty ? <p className={styles.empty}>Sem dados no período ainda.</p> : children}
    </section>
  );
}
