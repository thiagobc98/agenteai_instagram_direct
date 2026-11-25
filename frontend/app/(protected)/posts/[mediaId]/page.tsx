"use client";

// Uma postagem do Instagram e os comentários dela.

import { useParams } from "next/navigation";
import PostDetail from "../../../../components/comments/PostDetail";

export default function InstagramPostPage() {
  const { mediaId } = useParams<{ mediaId: string }>();
  return (
    <PostDetail
      channel="instagram"
      postId={decodeURIComponent(mediaId)}
      backLabel="Postagens"
    />
  );
}
