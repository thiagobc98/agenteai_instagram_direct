-- 005_appointment_reminders.sql
-- Rastreia lembretes de consulta já enviados aos pacientes (1 dia antes),
-- para o Worker não reenviar o mesmo lembrete em ticks seguintes do
-- scheduler diário ou após um restart.

CREATE TABLE IF NOT EXISTS appointment_reminders (
    event_id          TEXT PRIMARY KEY,        -- ID do evento no Google Calendar
    phone_number      TEXT NOT NULL,
    appointment_start TIMESTAMPTZ NOT NULL,
    sent_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
