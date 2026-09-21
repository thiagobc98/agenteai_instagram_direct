"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api, type ChatMessage } from "../../../../lib/api";
import { useChats } from "../../../../components/conversations/ChatsContext";
import ConversationHeader from "../../../../components/conversations/ConversationHeader";
import MessageList from "../../../../components/conversations/MessageList";
import MessageInput from "../../../../components/conversations/MessageInput";
import CustomerPanel from "../../../../components/conversations/CustomerPanel";
import { MessagesSkeleton } from "../../../../components/LoadingState";
import styles from "./page.module.css";

const POLL_MS = 5_000;

export default function ChatDetailPage() {
  const params = useParams<{ externalId: string }>();
  const externalId = decodeURIComponent(params.externalId);
  const { findChat } = useChats();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setInfoOpen(false);

    function fetchMessages() {
      api
        .chatMessages(externalId)
        .then((data) => {
          if (!cancelled) {
            setMessages(data.messages);
            setError(null);
          }
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }

    fetchMessages();
    const interval = setInterval(fetchMessages, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [externalId]);

  const chat = findChat(externalId);

  return (
    <div className={styles.wrap}>
      <div className={styles.conversation}>
        <ConversationHeader
          externalId={externalId}
          chat={chat}
          infoOpen={infoOpen}
          onToggleInfo={() => setInfoOpen((v) => !v)}
        />

        {error && <p className="error-text" style={{ padding: "0.6rem 1.1rem" }}>{error}</p>}

        {loading ? <MessagesSkeleton /> : <MessageList messages={messages} />}

        <MessageInput />
      </div>

      {infoOpen && (
        <CustomerPanel externalId={externalId} chat={chat} onClose={() => setInfoOpen(false)} />
      )}
    </div>
  );
}
