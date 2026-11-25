"use client";

// Um post da Página do Facebook e os comentários dele.

import { useParams } from "next/navigation";
import PostDetail from "../../../../components/comments/PostDetail";

export default function FacebookPostPage() {
  const { postId } = useParams<{ postId: string }>();
  return (
    <PostDetail
      channel="facebook"
      postId={decodeURIComponent(postId)}
      backLabel="Comentários do Facebook"
    />
  );
}
