import logging
import os
from typing import Any, Dict, Optional

from config import settings

logger = logging.getLogger(__name__)

try:
    from langfuse import Langfuse  # type: ignore
except Exception:
    Langfuse = None  # type: ignore


class LangfuseService:
    """
    Best-effort Langfuse integration.
    - Never breaks chat flow when SDK/env is unavailable.
    - Supports basic trace + generation logging for evaluation.
    """

    def __init__(self) -> None:
        self._client = None
        self._enabled = False
        self._llm_provider = None
        self._llm_base_url = None
        self._llm_connection = None
        self._llm_connection_template = None
        self._init_client()

    def _init_client(self) -> None:
        if Langfuse is None:
            logger.warning("Langfuse SDK not installed; tracing disabled.")
            return

        enabled = bool(getattr(settings, "LANGFUSE_ENABLED", False))
        public_key = (
            getattr(settings, "LANGFUSE_PUBLIC_KEY", None)
            or os.getenv("LANGFUSE_PUBLIC_KEY")
        )
        secret_key = (
            getattr(settings, "LANGFUSE_SECRET_KEY", None)
            or os.getenv("LANGFUSE_SECRET_KEY")
        )
        host = (
            getattr(settings, "LANGFUSE_HOST", None)
            or os.getenv("LANGFUSE_HOST")
            or "https://cloud.langfuse.com"
        )
        environment = (
            getattr(settings, "LANGFUSE_ENV", None)
            or os.getenv("LANGFUSE_ENV")
            or "development"
        )
        release = (
            getattr(settings, "LANGFUSE_RELEASE", None)
            or os.getenv("LANGFUSE_RELEASE")
            or None
        )
        self._llm_provider = (
            getattr(settings, "LANGFUSE_LLM_PROVIDER", None)
            or os.getenv("LANGFUSE_LLM_PROVIDER")
            or "openrouter"
        )
        self._llm_base_url = (
            getattr(settings, "LANGFUSE_LLM_BASE_URL", None)
            or os.getenv("LANGFUSE_LLM_BASE_URL")
            or "https://openrouter.ai/api/v1"
        )
        self._llm_connection = (
            getattr(settings, "LANGFUSE_LLM_CONNECTION", None)
            or os.getenv("LANGFUSE_LLM_CONNECTION")
        )
        self._llm_connection_template = (
            getattr(settings, "LANGFUSE_LLM_CONNECTION_TEMPLATE", None)
            or os.getenv("LANGFUSE_LLM_CONNECTION_TEMPLATE")
        )

        if not enabled:
            return
        if not public_key or not secret_key:
            logger.warning("Langfuse enabled but keys are missing; tracing disabled.")
            return

        try:
            kwargs: Dict[str, Any] = {
                "public_key": public_key,
                "secret_key": secret_key,
                "host": host,
            }
            # Keep optional fields permissive across SDK versions.
            if environment:
                kwargs["environment"] = environment
            if release:
                kwargs["release"] = release
            self._client = Langfuse(**kwargs)
            self._enabled = True
            logger.info("Langfuse tracing enabled.")
        except Exception as exc:
            logger.warning("Langfuse init failed; tracing disabled. error=%s", exc)
            self._client = None
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return bool(self._enabled and self._client is not None)

    def start_trace(
        self,
        *,
        name: str,
        user_id: Optional[str],
        session_id: Optional[str],
        model_id: Optional[str],
        input_text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        metadata_payload = dict(metadata or {})
        if model_id:
            metadata_payload.setdefault("model_id", model_id)
        metadata_payload.update(self._build_llm_metadata(model_id))
        try:
            trace = self._client.trace(
                name=name,
                user_id=user_id,
                session_id=session_id,
                input={"message": input_text},
                metadata=metadata_payload or None,
            )
            trace_id = getattr(trace, "id", None)
            return {"trace": trace, "trace_id": trace_id}
        except Exception as exc:
            logger.debug("Langfuse start_trace failed: %s", exc)
            return {}

    def log_success(
        self,
        trace_ctx: Dict[str, Any],
        *,
        model_id: str,
        input_text: str,
        output_text: str,
        usage: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        trace = trace_ctx.get("trace")
        trace_id = trace_ctx.get("trace_id")
        usage_payload = self._usage_payload(usage)
        meta = dict(metadata or {})
        if model_id:
            meta.setdefault("model_id", model_id)
        meta.update(self._build_llm_metadata(model_id))
        try:
            if trace is not None and hasattr(trace, "generation"):
                gen_kwargs: Dict[str, Any] = {
                    "name": "agent-response",
                    "model": model_id,
                    "input": {"message": input_text},
                    "output": {"message": output_text},
                    "metadata": meta or None,
                }
                if usage_payload:
                    gen_kwargs["usage_details"] = usage_payload
                trace.generation(**gen_kwargs)
                if hasattr(trace, "update"):
                    trace.update(output={"message": output_text}, metadata=meta or None)
            elif hasattr(self._client, "generation"):
                gen_kwargs = {
                    "name": "agent-response",
                    "model": model_id,
                    "input": {"message": input_text},
                    "output": {"message": output_text},
                    "metadata": meta or None,
                }
                if usage_payload:
                    gen_kwargs["usage_details"] = usage_payload
                if trace_id:
                    gen_kwargs["trace_id"] = trace_id
                self._client.generation(**gen_kwargs)
            self._flush()
        except Exception as exc:
            logger.debug("Langfuse log_success failed: %s", exc)

    def log_error(
        self,
        trace_ctx: Dict[str, Any],
        *,
        model_id: Optional[str],
        input_text: str,
        error_message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        trace = trace_ctx.get("trace")
        trace_id = trace_ctx.get("trace_id")
        meta = dict(metadata or {})
        if model_id:
            meta.setdefault("model_id", model_id)
        meta.update(self._build_llm_metadata(model_id))
        meta["error"] = error_message
        try:
            if trace is not None and hasattr(trace, "event"):
                trace.event(
                    name="agent-error",
                    input={"message": input_text},
                    output={"error": error_message},
                    metadata=meta,
                )
                if hasattr(trace, "update"):
                    trace.update(output={"error": error_message}, metadata=meta)
            elif hasattr(self._client, "event"):
                event_kwargs: Dict[str, Any] = {
                    "name": "agent-error",
                    "input": {"message": input_text},
                    "output": {"error": error_message},
                    "metadata": meta,
                }
                if trace_id:
                    event_kwargs["trace_id"] = trace_id
                self._client.event(**event_kwargs)
            self._flush()
        except Exception as exc:
            logger.debug("Langfuse log_error failed: %s", exc)

    def _usage_payload(self, usage: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(usage, dict):
            return {}
        prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        return {
            "input": prompt_tokens,
            "output": completion_tokens,
            "total": total_tokens,
        }

    def _base_model_id(self, model_id: Optional[str]) -> str:
        raw = str(model_id or "").strip()
        if not raw:
            return ""
        return raw.split(":", 1)[0]

    def _provider_from_model(self, model_id: Optional[str]) -> str:
        base = self._base_model_id(model_id)
        if "/" not in base:
            return (self._llm_provider or "openrouter").strip().lower()
        return base.split("/", 1)[0].strip().lower()

    def _resolve_llm_connection(self, model_id: Optional[str]) -> Optional[str]:
        base = self._base_model_id(model_id)
        if not base:
            return self._llm_connection

        provider = self._provider_from_model(base) or (self._llm_provider or "openrouter").strip().lower()
        template = str(self._llm_connection_template or "").strip()
        if template:
            try:
                return template.format(model=base, provider=provider)
            except Exception:
                return template

        explicit = str(self._llm_connection or "").strip()
        if explicit:
            if "{" in explicit and "}" in explicit:
                try:
                    return explicit.format(model=base, provider=provider)
                except Exception:
                    return explicit
            return explicit

        return f"{provider}/{base}"

    def _build_llm_metadata(self, model_id: Optional[str]) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        provider = self._provider_from_model(model_id)
        if provider:
            metadata["llm_provider"] = provider
        elif self._llm_provider:
            metadata["llm_provider"] = self._llm_provider
        if self._llm_base_url:
            metadata["llm_base_url"] = self._llm_base_url
        connection = self._resolve_llm_connection(model_id)
        if connection:
            metadata["llm_connection"] = connection
        return metadata

    def _flush(self) -> None:
        try:
            if self._client is not None and hasattr(self._client, "flush"):
                self._client.flush()
        except Exception:
            pass


langfuse_service = LangfuseService()
