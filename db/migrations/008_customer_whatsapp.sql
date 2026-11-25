-- 008_customer_whatsapp.sql
-- WhatsApp da cliente, coletado pelo agente antes de encaminhar para a
-- Patrícia (preço, pagamento, frete, estoque, troca, etc.).
--
-- Guardado normalizado (só dígitos, com código do país 55 na frente — ex:
-- "5531999998888"), pronto para montar um link "https://wa.me/<numero>" no
-- painel. Ver `shared/contacts.py` (normalize_whatsapp/set_customer_whatsapp)
-- e a tool `save_customer_whatsapp` (agents/tools/handoff.py).

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS whatsapp TEXT;
