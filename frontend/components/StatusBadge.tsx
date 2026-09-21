import { IconAlertCircle, IconCheck, IconClock, IconInfo } from "./icons";
import styles from "./StatusBadge.module.css";

const CONFIG: Record<string, { label: string; tone: "success" | "warning" | "danger" | "neutral" }> = {
  done: { label: "Concluída", tone: "success" },
  processing: { label: "Processando", tone: "warning" },
  queued: { label: "Na fila", tone: "neutral" },
  failed: { label: "Falhou", tone: "danger" },
};

export default function StatusBadge({ status }: { status: string }) {
  const config = CONFIG[status] ?? { label: status, tone: "neutral" as const };

  return (
    <span className={`${styles.badge} ${styles[config.tone]}`}>
      {config.tone === "success" && <IconCheck size={12} />}
      {config.tone === "warning" && <IconClock size={12} />}
      {config.tone === "danger" && <IconAlertCircle size={12} />}
      {config.tone === "neutral" && <IconInfo size={12} />}
      {config.label}
    </span>
  );
}
