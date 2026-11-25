import type { Chat } from "../../lib/api";
import Avatar from "../Avatar";
import {
  contactLabel,
  formatAgentName,
  formatDateTime,
  formatWhatsapp,
  relativeTime,
  whatsappLink,
} from "../../lib/format";
import { IconPhone, IconX } from "../icons";
import styles from "./CustomerPanel.module.css";

export default function CustomerPanel({
  externalId,
  chat,
  onClose,
}: {
  externalId: string;
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
        <Avatar seed={externalId} size={72} src={chat?.profile_pic_url} />
        <p className={styles.name}>
          {chat ? contactLabel(chat) : contactLabel({ external_id: externalId })}
        </p>
        {chat?.name && chat.username && <p className="muted">{chat.name}</p>}
        <p className="muted">ID Instagram: {externalId}</p>
        {chat?.username && (
          <a
            href={`https://instagram.com/${chat.username}`}
            target="_blank"
            rel="noreferrer"
            className="muted"
          >
            Abrir perfil no Instagram
          </a>
        )}
      </div>

      {!chat ? (
        <p className="muted" style={{ padding: "0 1.2rem" }}>
          Carregando dados da conversa...
        </p>
      ) : (
        <>
          {chat.whatsapp && (
            <div className={styles.section}>
              <span className={styles.sectionTitle}>Contato</span>
              <a
                href={whatsappLink(chat.whatsapp) ?? undefined}
                target="_blank"
                rel="noreferrer"
                className={styles.whatsappLink}
              >
                <IconPhone size={16} />
                {formatWhatsapp(chat.whatsapp)}
              </a>
            </div>
          )}

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
