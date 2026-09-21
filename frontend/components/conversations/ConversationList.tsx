"use client";

import { usePathname } from "next/navigation";
import { useChats } from "./ChatsContext";
import ConversationItem from "./ConversationItem";
import { ConversationListSkeleton } from "../LoadingState";
import EmptyState from "../EmptyState";
import { IconChats, IconSearch } from "../icons";
import styles from "./ConversationList.module.css";

export default function ConversationList({ className }: { className?: string }) {
  const pathname = usePathname();
  const activeExternalId = pathname.startsWith("/chats/")
    ? decodeURIComponent(pathname.replace("/chats/", ""))
    : null;

  const { filteredChats, total, loading, error, search, setSearch, hasMore, loadMore, loadingMore } =
    useChats();

  return (
    <div className={`${styles.panel} ${className ?? ""}`}>
      <div className={styles.header}>
        <h1 className={styles.title}>Conversas</h1>
        <span className="muted">{total}</span>
      </div>

      <div className={styles.searchWrap}>
        <IconSearch size={16} className={styles.searchIcon} />
        <input
          className={styles.searchInput}
          placeholder="Buscar por ID ou mensagem..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {error && <p className="error-text" style={{ padding: "0 1rem" }}>{error}</p>}

      <div className={styles.list}>
        {loading && <ConversationListSkeleton />}

        {!loading && filteredChats.length === 0 && !error && (
          <EmptyState
            icon={<IconChats size={22} />}
            title={search ? "Nenhum resultado" : "Nenhuma conversa"}
            description={
              search
                ? "Tente buscar por outro ID ou termo."
                : "Quando novas conversas chegarem, elas aparecerão aqui."
            }
          />
        )}

        {filteredChats.map((chat) => (
          <ConversationItem
            key={`${chat.external_id}:${chat.agent_id}`}
            chat={chat}
            active={chat.external_id === activeExternalId}
          />
        ))}

        {!loading && !search && hasMore && (
          <button
            className={styles.loadMore}
            onClick={loadMore}
            disabled={loadingMore}
          >
            {loadingMore ? "Carregando..." : "Carregar mais"}
          </button>
        )}
      </div>
    </div>
  );
}
