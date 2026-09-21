import { IconPaperclip, IconSend } from "../icons";
import styles from "./MessageInput.module.css";

// O envio de mensagens pelo painel não existe no backend hoje: o agente de
// IA responde automaticamente às mensagens recebidas via WhatsApp. Mantemos
// o composer visível (para consistência do layout tipo WhatsApp Web) porém
// desabilitado, em vez de simular um envio que não tem efeito real.
export default function MessageInput() {
  return (
    <div className={styles.wrap} title="Envio pelo painel ainda não disponível nesta fase">
      <button className={styles.iconButton} disabled type="button">
        <IconPaperclip size={18} />
      </button>
      <input
        className={styles.input}
        placeholder="Envio pelo painel indisponível — respostas são automáticas"
        disabled
      />
      <button className={styles.sendButton} disabled type="button">
        <IconSend size={16} />
      </button>
    </div>
  );
}
