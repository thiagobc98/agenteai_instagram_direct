"use client";

import { usePathname } from "next/navigation";
import { ChatsProvider } from "../../../components/conversations/ChatsContext";
import ConversationList from "../../../components/conversations/ConversationList";
import styles from "./layout.module.css";

export default function ChatsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const hasSelection = pathname !== "/chats";

  return (
    <ChatsProvider>
      <div className={styles.shell}>
        <ConversationList
          className={hasSelection ? styles.listHiddenOnMobile : undefined}
        />
        <div className={`${styles.detail} ${hasSelection ? "" : styles.detailHiddenOnMobile}`}>
          {children}
        </div>
      </div>
    </ChatsProvider>
  );
}
