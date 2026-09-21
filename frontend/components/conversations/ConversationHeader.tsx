import Link from "next/link";
import type { Chat } from "../../lib/api";
import Avatar from "../Avatar";
import { formatAgentName, formatContactId, relativeTime } from "../../lib/format";
import { IconArrowLeft, IconInfo } from "../icons";
import styles from "./ConversationHeader.module.css";

export default function ConversationHeader({
  externalId,
  chat,
  infoOpen,
  onToggleInfo,
}: {
  externalId: string;
  chat?: Chat;
  infoOpen: boolean;
  onToggleInfo: () => void;
}) {
  return (
    <div className={styles.header}>
      <Link href="/chats" className={styles.backButton} aria-label="Voltar para conversas">
        <IconArrowLeft size={18} />
      </Link>

      <Avatar seed={externalId} size={40} />

      <div className={styles.info}>
        <p className={styles.name}>{formatContactId(externalId)}</p>
        <p className={styles.sub}>
          {chat ? (
            <>
              {formatAgentName(chat.agent_id)} · última atividade {relativeTime(chat.last_message_at)}
            </>
          ) : (
            "Carregando..."
          )}
        </p>
      </div>

      <button
        className={`${styles.infoButton} ${infoOpen ? styles.infoButtonActive : ""}`}
        onClick={onToggleInfo}
        title="Informações do contato"
      >
        <IconInfo size={18} />
      </button>
    </div>
  );
}
