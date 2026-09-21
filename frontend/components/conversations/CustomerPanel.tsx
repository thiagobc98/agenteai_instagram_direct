import type { Chat } from "../../lib/api";
import Avatar from "../Avatar";
import { formatAgentName, formatDateTime, formatPhone, relativeTime } from "../../lib/format";
import { IconX } from "../icons";
import styles from "./CustomerPanel.module.css";

export default function CustomerPanel({
  phone,
  chat,
  onClose,
}: {
  phone: string;
  chat?: Chat;
  onClose: () => void;
}) {
  return (
    <aside className={styles.panel}>
      <div className={styles.header}>
        <span className={styles.title}>Informações</span>
        <button className={styles.closeButton} onClick={onClose} aria-label="Fechar painel">
          <IconX size={16} />
        </button>
      </div>

      <div className={styles.profile}>
        <Avatar seed={phone} size={72} />
        <p className={styles.name}>{formatPhone(phone)}</p>
        <p className="muted">{phone}</p>
      </div>

      {!chat ? (
        <p className="muted" style={{ padding: "0 1.2rem" }}>
          Carregando dados da conversa...
        </p>
      ) : (
        <>
          <div className={styles.section}>
            <span className={styles.sectionTitle}>Atendimento</span>
            <dl className={styles.list}>
              <div className={styles.row}>
                <dt>Agente</dt>
                <dd>{formatAgentName(chat.agent_id)}</dd>
              </div>
              <div className={styles.row}>
                <dt>Thread</dt>
                <dd className={styles.mono}>{chat.thread_id}</dd>
              </div>
            </dl>
          </div>

          <div className={styles.section}>
            <span className={styles.sectionTitle}>Atividade</span>
            <dl className={styles.list}>
              <div className={styles.row}>
                <dt>Cliente desde</dt>
                <dd>{formatDateTime(chat.created_at)}</dd>
              </div>
              <div className={styles.row}>
                <dt>Última atividade</dt>
                <dd>{relativeTime(chat.last_message_at)}</dd>
              </div>
              <div className={styles.row}>
                <dt>Mensagens trocadas</dt>
                <dd>{chat.message_count}</dd>
              </div>
            </dl>
          </div>
        </>
      )}
    </aside>
  );
}
