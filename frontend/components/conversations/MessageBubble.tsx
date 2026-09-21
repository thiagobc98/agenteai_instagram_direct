import { IconAlertCircle, IconCheck, IconClock, IconMic, IconPhoto } from "../icons";
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
}

export default function MessageBubble({ data }: { data: BubbleData }) {
  const isUser = data.side === "user";

  return (
    <div className={`${styles.row} ${isUser ? styles.left : styles.right}`}>
      <div
        className={`${styles.bubble} ${isUser ? styles.userBubble : styles.agentBubble} ${
          data.failed ? styles.failedBubble : ""
        }`}
      >
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
