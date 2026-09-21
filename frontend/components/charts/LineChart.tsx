import { niceMax } from "./scale";
import styles from "./charts.module.css";

const W = 720;
const H = 300;
const PAD = { top: 14, right: 14, bottom: 26, left: 34 };

export interface LineSeries {
  name: string;
  color: string;
  values: number[];
  area?: boolean;
}

// Gráfico de linhas em SVG com várias séries na mesma escala. A primeira
// série marcada com `area` ganha um preenchimento suave.
export default function LineChart({
  labels,
  series,
}: {
  labels: string[];
  series: LineSeries[];
}) {
  const all = series.flatMap((s) => s.values);
  const top = niceMax(Math.max(...all, 0));
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const n = labels.length;
  const x = (i: number) => PAD.left + (n === 1 ? plotW / 2 : (plotW * i) / (n - 1));
  const y = (v: number) => PAD.top + plotH - (v / top) * plotH;
  const ticks = [0, top / 2, top];
  const labelEvery = Math.max(1, Math.ceil(n / 8));

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={styles.svg}
      role="img"
      aria-label="Gráfico de linhas por dia"
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

      {labels.map(
        (label, i) =>
          i % labelEvery === 0 && (
            <text
              key={label}
              x={x(i)}
              y={H - 8}
              textAnchor="middle"
              className={styles.axis}
            >
              {label}
            </text>
          ),
      )}

      {series.map((s) => {
        const points = s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
        const areaPath = `M${x(0)},${y(0)} L${points.replaceAll(" ", " L")} L${x(n - 1)},${y(0)} Z`;
        return (
          <g key={s.name}>
            {s.area && <path d={areaPath} fill={s.color} opacity={0.12} />}
            <polyline
              points={points}
              fill="none"
              stroke={s.color}
              strokeWidth={2.5}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {s.values.map((v, i) => (
              <circle key={i} cx={x(i)} cy={y(v)} r={3.4} fill="#fff" stroke={s.color} strokeWidth={2}>
                <title>{`${labels[i]} · ${s.name}: ${v}`}</title>
              </circle>
            ))}
          </g>
        );
      })}
    </svg>
  );
}
