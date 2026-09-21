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
  const params = useParams<{ phone: string }>();
  const phone = decodeURIComponent(params.phone);
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
        .chatMessages(phone)
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
  }, [phone]);

  const chat = findChat(phone);

  return (
    <div className={styles.wrap}>
      <div className={styles.conversation}>
        <ConversationHeader
          phone={phone}
          chat={chat}
          infoOpen={infoOpen}
          onToggleInfo={() => setInfoOpen((v) => !v)}
        />

        {error && <p className="error-text" style={{ padding: "0.6rem 1.1rem" }}>{error}</p>}

        {loading ? <MessagesSkeleton /> : <MessageList messages={messages} />}

        <MessageInput />
      </div>

      {infoOpen && (
        <CustomerPanel phone={phone} chat={chat} onClose={() => setInfoOpen(false)} />
      )}
    </div>
  );
}
