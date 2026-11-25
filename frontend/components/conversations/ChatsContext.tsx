"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { api, type Chat } from "../../lib/api";

const PAGE_SIZE = 50;
const POLL_MS = 8_000;

interface ChatsContextValue {
  chats: Chat[];
  filteredChats: Chat[];
  total: number;
  loading: boolean;
  error: string | null;
  search: string;
  setSearch: (value: string) => void;
  hasMore: boolean;
  loadMore: () => void;
  loadingMore: boolean;
  findChat: (externalId: string) => Chat | undefined;
}

const ChatsContext = createContext<ChatsContextValue | null>(null);

export function ChatsProvider({ children }: { children: React.ReactNode }) {
  const [chats, setChats] = useState<Chat[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let cancelled = false;

    function fetchChats(isInitial: boolean) {
      if (isInitial) setLoading(true);
      api
        .chats(limit, 0)
        .then((data) => {
          if (cancelled) return;
          setChats(data.chats);
          setTotal(data.total);
          setError(null);
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        })
        .finally(() => {
          if (!cancelled) {
            setLoading(false);
            setLoadingMore(false);
          }
        });
    }

    fetchChats(true);
    const interval = setInterval(() => fetchChats(false), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [limit]);

  const filteredChats = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return chats;
    return chats.filter(
      (chat) =>
        chat.external_id.toLowerCase().includes(term) ||
        (chat.username ?? "").toLowerCase().includes(term.replace(/^@/, "")) ||
        (chat.name ?? "").toLowerCase().includes(term) ||
        (chat.last_message ?? "").toLowerCase().includes(term) ||
        chat.agent_id.toLowerCase().includes(term),
    );
  }, [chats, search]);

  function loadMore() {
    setLoadingMore(true);
    setLimit((prev) => prev + PAGE_SIZE);
  }

  function findChat(externalId: string) {
    return chats.find((c) => c.external_id === externalId);
  }

  const value: ChatsContextValue = {
    chats,
    filteredChats,
    total,
    loading,
    error,
    search,
    setSearch,
    hasMore: chats.length < total,
    loadMore,
    loadingMore,
    findChat,
  };

  return <ChatsContext.Provider value={value}>{children}</ChatsContext.Provider>;
}

export function useChats() {
  const ctx = useContext(ChatsContext);
  if (!ctx) throw new Error("useChats deve ser usado dentro de ChatsProvider");
  return ctx;
}
