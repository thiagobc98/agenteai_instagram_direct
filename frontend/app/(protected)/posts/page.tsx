"use client";

// Comentários das postagens do Instagram (fila de aprovação + postagens).

import { api } from "../../../lib/api";
import CommentsWorkspace from "../../../components/comments/CommentsWorkspace";

export default function PostsPage() {
  return (
    <CommentsWorkspace
      channel="instagram"
      title="Postagens e comentários"
      subtitle="A IA escreve um rascunho para cada comentário novo. Revise e aprove antes de publicar."
      sync={api.syncPosts}
    />
  );
}
