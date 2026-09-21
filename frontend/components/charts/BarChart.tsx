import { niceMax } from "./scale";
import styles from "./charts.module.css";

const H = 210;
const PAD = { top: 12, right: 8, bottom: 26, left: 34 };

// Gráfico de colunas em SVG. O maior valor é destacado; os demais ficam mais
// claros — assim o "pico" salta aos olhos sem precisar ler os números.
export default function BarChart({
  values,
  labels,
  labelEvery = 1,
  color = "var(--chart-1)",
  unit = "mensagens",
  width = 600,
}: {
  values: number[];
  labels: string[];
  labelEvery?: number;
  color?: string;
  unit?: string;
  // Largura do viewBox: use ~340 em cartões estreitos para o texto não encolher.
  width?: number;
}) {
  const W = width;
  const top = niceMax(Math.max(...values, 0));
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const slot = plotW / values.length;
  const barW = Math.min(slot * 0.62, 34);
  const peak = Math.max(...values, 0);
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH;
  const ticks = [0, top / 2, top];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={styles.svg}
      role="img"
      aria-label={`Gráfico de colunas de ${unit}`}
    >
      {ticks.map((t) => (
        <g key={t}>
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(t)}
            y2={y(t)}
            className={styles.grid}
          />
          <text x={PAD.left - 6} y={y(t) + 4} textAnchor="end" className={styles.axis}>
            {Math.round(t)}
          </text>
        </g>
      ))}

      {values.map((v, i) => {
        const x = PAD.left + slot * i + (slot - barW) / 2;
        const isPeak = v > 0 && v === peak;
        return (
          <g key={i}>
            <rect
              x={x}
              y={y(v)}
              width={barW}
              height={Math.max(PAD.top + plotH - y(v), v > 0 ? 2 : 0)}
              rx={3}
              fill={color}
              opacity={isPeak ? 1 : 0.5}
            >
              <title>{`${labels[i]}: ${v} ${unit}`}</title>
            </rect>
            {i % labelEvery === 0 && (
              <text
                x={x + barW / 2}
                y={H - 8}
                textAnchor="middle"
                className={styles.axis}
              >
                {labels[i]}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}
