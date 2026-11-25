import Link from "next/link";
import type { Chat } from "../../lib/api";
import Avatar from "../Avatar";
import { contactLabel, formatAgentName, relativeTime } from "../../lib/format";
import styles from "./ConversationItem.module.css";

export default function ConversationItem({
  chat,
  active,
}: {
  chat: Chat;
  active: boolean;
}) {
  return (
    <Link
      href={`/chats/${encodeURIComponent(chat.external_id)}`}
      className={`${styles.item} ${active ? styles.active : ""}`}
    >
      <Avatar seed={chat.external_id} size={44} src={chat.profile_pic_url} />
      <div className={styles.body}>
        <div className={styles.row}>
          <span className={styles.name}>{contactLabel(chat)}</span>
          <span className={styles.time}>{relativeTime(chat.last_message_at)}</span>
        </div>
        <div className={styles.row}>
          <span className={styles.preview}>{chat.last_message ?? "Sem mensagens"}</span>
          <span className={styles.agentTag}>{formatAgentName(chat.agent_id)}</span>
        </div>
      </div>
    </Link>
  );
}
