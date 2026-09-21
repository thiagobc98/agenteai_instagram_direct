"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "../../lib/api";
import { formatDateSeparator, formatTime } from "../../lib/format";
import MessageBubble, { type BubbleData } from "./MessageBubble";
import EmptyState from "../EmptyState";
import { IconChats } from "../icons";
import styles from "./MessageList.module.css";

interface Group {
  dateKey: string;
  dateLabel: string;
  bubbles: BubbleData[];
}

function buildGroups(messages: ChatMessage[]): Group[] {
  // A API retorna mais recente -> mais antigo; aqui exibimos em ordem cronológica.
  const ordered = [...messages].reverse();
  const groups: Group[] = [];

  for (const msg of ordered) {
    const userTime = msg.created_at ?? msg.processed_at;
    const dateKey = userTime ? new Date(userTime).toDateString() : "unknown";

    let group = groups.find((g) => g.dateKey === dateKey);
    if (!group) {
      group = { dateKey, dateLabel: formatDateSeparator(userTime), bubbles: [] };
      groups.push(group);
    }

    const mediaLabel = msg.media_type;

    group.bubbles.push({
      id: `${msg.id}-user`,
      side: "user",
      text: msg.incoming_message || msg.normalized_input || "",
      time: formatTime(msg.created_at),
      mediaType: mediaLabel,
    });

    if (msg.status === "failed") {
      group.bubbles.push({
        id: `${msg.id}-agent`,
        side: "agent",
        text: msg.response || "",
        time: formatTime(msg.processed_at ?? msg.created_at),
        failed: true,
        errorText: msg.error || msg.media_processing_error || "Falha no processamento",
      });
    } else if (msg.status === "done") {
      group.bubbles.push({
        id: `${msg.id}-agent`,
        side: "agent",
        text: msg.response || "",
        time: formatTime(msg.processed_at),
      });
    } else {
      group.bubbles.push({
        id: `${msg.id}-agent`,
        side: "agent",
        text: msg.status === "processing" ? "Processando..." : "Na fila...",
        time: formatTime(msg.created_at),
        pending: true,
      });
    }
  }

  return groups;
}

export default function MessageList({ messages }: { messages: ChatMessage[] }) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  if (messages.length === 0) {
    return (
      <EmptyState
        icon={<IconChats size={22} />}
        title="Nenhuma mensagem para este contato"
        description="As mensagens trocadas com este número aparecerão aqui."
      />
    );
  }

  const groups = buildGroups(messages);

  return (
    <div className={styles.list}>
      {groups.map((group) => (
        <div key={group.dateKey}>
          <div className={styles.separator}>
            <span>{group.dateLabel}</span>
          </div>
          {group.bubbles.map((bubble) => (
            <MessageBubble key={bubble.id} data={bubble} />
          ))}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
