import EmptyState from "../../../components/EmptyState";
import { IconChats } from "../../../components/icons";
import styles from "./page.module.css";

export default function ChatsIndexPage() {
  return (
    <div className={styles.fill}>
      <EmptyState
        icon={<IconChats size={26} />}
        title="Selecione uma conversa"
        description="Escolha um contato na lista ao lado para ver o histórico de mensagens."
      />
    </div>
  );
}
