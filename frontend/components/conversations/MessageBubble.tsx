import {
  IconAlertCircle,
  IconCheck,
  IconClock,
  IconExternal,
  IconMic,
  IconPhoto,
} from "../icons";
import styles from "./MessageBubble.module.css";

export interface BubbleData {
  id: string;
  side: "user" | "agent";
  text: string;
  time: string;
  mediaType?: string | null;
  pending?: boolean;
  failed?: boolean;
  errorText?: string | null;
  /** Selo acima do texto (ex: "Comentou no post"). */
  label?: string;
  /** Link opcional ao lado do selo (ex: o post comentado). */
  href?: string | null;
  /** "comment": texto de um comentário público, não mensagem do Direct. */
  variant?: "comment";
}

export default function MessageBubble({ data }: { data: BubbleData }) {
  const isUser = data.side === "user";

  return (
    <div className={`${styles.row} ${isUser ? styles.left : styles.right}`}>
      <div
        className={`${styles.bubble} ${isUser ? styles.userBubble : styles.agentBubble} ${
          data.failed ? styles.failedBubble : ""
        } ${data.variant === "comment" ? styles.commentBubble : ""}`}
      >
        {data.label && (
          <span className={styles.label}>
            {data.label}
            {data.href && (
              <a href={data.href} target="_blank" rel="noopener noreferrer" className={styles.labelLink}>
                ver post <IconExternal size={11} />
              </a>
            )}
          </span>
        )}

        {data.mediaType && (
          <span className={styles.mediaChip}>
            {data.mediaType.startsWith("audio") ? <IconMic size={13} /> : <IconPhoto size={13} />}
            {data.mediaType}
          </span>
        )}

        {data.text && <p className={styles.text}>{data.text}</p>}

        {data.failed && data.errorText && (
          <p className={styles.errorText}>
            <IconAlertCircle size={12} /> {data.errorText}
          </p>
        )}

        <div className={styles.meta}>
          {data.pending && <IconClock size={11} />}
          {!isUser && !data.pending && !data.failed && <IconCheck size={11} />}
          <span>{data.time}</span>
        </div>
      </div>
    </div>
  );
}
