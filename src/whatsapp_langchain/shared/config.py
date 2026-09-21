"""Configuração centralizada via variáveis de ambiente.

Usa pydantic-settings para carregar, validar e tipar todas as configurações
do projeto a partir de variáveis de ambiente ou arquivo .env.

Uso:
    from whatsapp_langchain.shared.config import settings

    print(settings.database_url)
    print(settings.rate_limit_per_hour)

Todas as configurações têm defaults sensatos para desenvolvimento local.
Em produção, configure via variáveis de ambiente ou .env.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações do projeto carregadas de variáveis de ambiente.

    Cada campo corresponde a uma env var (case-insensitive).
    Ex: database_url → DATABASE_URL
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    database_url: str = (
        "postgresql://postgres:postgres@localhost:5432/whatsapp_langchain"
    )

    # --- Server ---
    port: int = 8000
    log_level: str = "info"
    log_json: bool = False  # True em prod para logs estruturados

    # --- Evolution API (WhatsApp) ---
    # URL base da instância Evolution API na sua VPS (ex: https://evo.seudominio.com)
    evolution_base_url: str = ""
    # apikey da instância (Settings -> API Key no manager, ou definida na criação)
    evolution_api_key: str = ""
    # Nome da instância conectada ao WhatsApp
    evolution_instance: str = ""
    # Token secreto próprio (não vem do Evolution) usado para validar que o
    # POST em /webhook/evolution/{token} realmente veio da sua instância —
    # o Evolution não assina os webhooks como o Twilio faz.
    evolution_webhook_token: str = ""

    # --- Rate Limit ---
    rate_limit_per_hour: int = 30

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Frontend ---
    frontend_origin: str = "http://localhost:3000"

    # --- Admin Auth ---
    admin_username: str = "admin"
    admin_password: SecretStr | None = None
    # Gere um valor forte em produção:
    # python -c "import secrets;print(secrets.token_hex(32))"
    session_secret_key: SecretStr = SecretStr("dev-insecure-secret-change-me")
    session_max_age_seconds: int = 28800
    session_cookie_secure: bool = False

    # --- Debounce ---
    message_buffer_seconds: float = 2.0

    # --- LLM (OpenRouter) ---
    # Todas as chamadas LLM, embeddings e transcrição usam OpenRouter
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "x-ai/grok-4.3"
    # Modelo dedicado ao pré-processamento de mídia (imagem/áudio)
    openrouter_midia_model: str = "google/gemini-2.5-flash-lite"
    # OpenRouter reserva créditos com base em max_tokens, não no uso real —
    # sem um teto, o default do modelo (ex: 65536) pode exceder o saldo
    # disponível mesmo em respostas curtas.
    openrouter_max_tokens: int = 4096

    # --- LLM Rate Limit ---
    llm_rate_limit_requests_per_second: float = 0.5
    llm_rate_limit_max_burst: int = 10

    # --- Worker ---
    poll_interval_seconds: float = 1.0
    lease_seconds: int = 60
    max_attempts: int = 3

    # --- Media ---
    media_image_enabled: bool = True
    media_audio_enabled: bool = True

    # --- Context Management (migrado do .env manual) ---
    context_strategy: str = "trim"
    trim_keep_turns: int = 5
    summarize_trigger_tokens: int = 4000
    summarize_keep_messages: int = 10
    summarize_model: str = "x-ai/grok-4.1-fast"

    # --- Semantic Memory (LangGraph Store) ---
    memory_enabled: bool = True
    # Nome do modelo no OpenRouter (sem prefixo "openai:")
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dims: int = 1536
    memory_search_limit: int = 5

    # --- Google Calendar (agendamento) ---
    google_calendar_enabled: bool = False
    # Credenciais de Service Account: preencha UMA das duas opções.
    # JSON completo em uma linha só (ex: Railway, onde montar arquivo não é
    # simples) — tem prioridade sobre o arquivo se ambos estiverem definidos.
    google_service_account_json: str = ""
    # Caminho para o arquivo .json da service account (ex: docker-compose
    # local, via volume montado).
    google_service_account_file: str = ""
    # ID do calendário (e-mail da conta Google, ou "primary" se a service
    # account for dona do calendário). A agenda precisa estar compartilhada
    # com o e-mail da service account, com permissão de "fazer alterações".
    google_calendar_id: str = ""
    # Fuso horário usado para interpretar datas/horários do agendamento.
    business_timezone: str = "America/Sao_Paulo"
    # Janela de atendimento (hora cheia, 0-23) e duração padrão da consulta.
    business_hour_start: int = 9
    business_hour_end: int = 18
    appointment_duration_minutes: int = 30

    # --- Notificações proativas (fora do ciclo normal de webhook) ---
    # WhatsApp da médica (E.164) para receber a agenda do dia seguinte a
    # cada agendamento/remarcação/cancelamento. Vazio desabilita o aviso.
    doctor_whatsapp_number: str = ""
    # Hora (0-23, fuso business_timezone) em que os pacientes com consulta
    # no dia seguinte recebem o lembrete de confirmação.
    patient_reminder_hour: int = 9
    # Hora (0-23, fuso business_timezone) em que a médica recebe o resumo
    # fixo com a agenda do dia seguinte.
    doctor_summary_hour: int = 20


# Singleton — importar de qualquer lugar do projeto
settings = Settings()
