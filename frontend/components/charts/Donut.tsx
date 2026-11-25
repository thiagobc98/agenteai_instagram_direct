import { formatNumber } from "../../lib/format";
import styles from "./charts.module.css";

export interface DonutSegment {
  label: string;
  value: number;
  color: string;
}

const SIZE = 150;
const STROKE = 24;
const R = (SIZE - STROKE) / 2;
const CIRC = 2 * Math.PI * R;

// Rosca em SVG com legenda (quantidade e percentual de cada fatia).
export default function Donut({ segments }: { segments: DonutSegment[] }) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  let offset = 0;

  return (
    <div className={styles.donutWrap}>
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className={styles.donut}
        role="img"
        aria-label="Distribuição por tipo de mensagem"
      >
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={R}
          fill="none"
          stroke="var(--surface-alt)"
          strokeWidth={STROKE}
        />
        {segments.map((s) => {
          const len = total ? (s.value / total) * CIRC : 0;
          const circle = (
            <circle
              key={s.label}
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={R}
              fill="none"
              stroke={s.color}
              strokeWidth={STROKE}
              strokeDasharray={`${len} ${CIRC - len}`}
              strokeDashoffset={-offset}
              transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
            >
              <title>{`${s.label}: ${s.value}`}</title>
            </circle>
          );
          offset += len;
          return circle;
        })}
        <text x="50%" y="48%" textAnchor="middle" className={styles.donutTotal}>
          {formatNumber(total)}
        </text>
        <text x="50%" y="62%" textAnchor="middle" className={styles.axis}>
          mensagens
        </text>
      </svg>

      <ul className={styles.legend}>
        {segments.map((s) => (
          <li key={s.label}>
            <span className={styles.dot} style={{ background: s.color }} />
            <span>{s.label}</span>
            <strong>
              {formatNumber(s.value)}
              <small> · {total ? Math.round((s.value / total) * 100) : 0}%</small>
            </strong>
          </li>
        ))}
      </ul>
    </div>
  );
}
