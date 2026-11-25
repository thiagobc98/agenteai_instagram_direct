import Link from "next/link";
import type { Chat } from "../../lib/api";
import Avatar from "../Avatar";
import {
  contactLabel,
  formatAgentName,
  relativeTime,
  whatsappLink,
} from "../../lib/format";
import { IconArrowLeft, IconInfo, IconPhone } from "../icons";
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

      <Avatar seed={externalId} size={40} src={chat?.profile_pic_url} />

      <div className={styles.info}>
        <p className={styles.name}>
          {chat ? contactLabel(chat) : contactLabel({ external_id: externalId })}
        </p>
        <p className={styles.sub}>
          {chat ? (
            <>
              {chat.name ? `${chat.name} · ` : ""}
              {formatAgentName(chat.agent_id)} · última atividade {relativeTime(chat.last_message_at)}
            </>
          ) : (
            "Carregando..."
          )}
        </p>
      </div>

      {chat && whatsappLink(chat.whatsapp) && (
        <a
          href={whatsappLink(chat.whatsapp) ?? undefined}
          target="_blank"
          rel="noreferrer"
          className={styles.whatsappButton}
          title="Chamar no WhatsApp"
        >
          <IconPhone size={17} />
        </a>
      )}

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
