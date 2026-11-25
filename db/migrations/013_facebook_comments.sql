-- 013_facebook_comments.sql
-- Comentários dos posts da Página do Facebook, na mesma estrutura dos do
-- Instagram (rascunho da IA + aprovação no painel), numa tela própria.
--
-- Em vez de duplicar tabelas e código, `ig_posts` e `ig_comments` ganham a
-- coluna `channel`. Tudo o que já existe é do Instagram (DEFAULT), então o
-- comportamento atual não muda. Os nomes das tabelas ficam como estão para
-- não arriscar uma migração de renome.
--
-- Os IDs não colidem entre canais: no Facebook o post é "<page>_<post>" e o
-- comentário "<post>_<comment>"; no Instagram são numéricos puros.

ALTER TABLE ig_posts
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'instagram';
ALTER TABLE ig_comments
    ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'instagram';

-- Nomeados para o ALTER ser reexecutável (IF NOT EXISTS não vale para CHECK)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ig_posts_channel_check') THEN
        ALTER TABLE ig_posts ADD CONSTRAINT ig_posts_channel_check
            CHECK (channel IN ('instagram', 'facebook'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ig_comments_channel_check') THEN
        ALTER TABLE ig_comments ADD CONSTRAINT ig_comments_channel_check
            CHECK (channel IN ('instagram', 'facebook'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ig_comments_channel_status
    ON ig_comments (channel, status, commented_at);
CREATE INDEX IF NOT EXISTS idx_ig_posts_channel
    ON ig_posts (channel, posted_at DESC);
