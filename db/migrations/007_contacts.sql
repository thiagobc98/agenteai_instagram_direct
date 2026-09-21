-- 007_contacts.sql
-- Perfil público dos clientes do Instagram (@username, nome e foto).
--
-- O webhook só traz o IGSID (número opaco). O worker consulta a User Profile
-- API da Meta na primeira mensagem de cada contato (e a cada refresh) e guarda
-- o resultado aqui, para o painel mostrar o @ em vez do número.
-- `fetched_at` permite renovar perfis antigos (o @ e a foto podem mudar).

CREATE TABLE IF NOT EXISTS contacts (
    external_id     TEXT PRIMARY KEY,
    username        TEXT,
    name            TEXT,
    profile_pic_url TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
