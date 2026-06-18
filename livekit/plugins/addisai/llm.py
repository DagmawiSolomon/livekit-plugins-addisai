

import os
import json
import logging
from typing import Any
from dataclasses import dataclass

import httpx

from enum import Enum
from livekit.agents import llm
from livekit.agents.llm import ChatContext, Tool, ToolChoice, ChatChunk, ChoiceDelta, ChatRole
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import is_given
from livekit.agents._exceptions import APIError
from livekit.agents.llm import LLMStream as BaseLLMStream

from .constants import API_BASE_URL

DEFAULT_LLM_URL = f"{API_BASE_URL}/api/v1/chat_generate"

logger = logging.getLogger(__name__)


class ADDIS_AI_LLM_LANGUAGES(str, Enum):
    AM = "am"
    OM = "om"

@dataclass(frozen=True)
class LLMOptions:
    api_key: str
    base_url: str
    language: ADDIS_AI_LLM_LANGUAGES

    temperature: float | None
    top_p: float | None
    top_k: int | None
    max_output_tokens: int | None

class LLM(llm.LLM):
    def __init__(
            self,
            *, 
            language: ADDIS_AI_LLM_LANGUAGES, 
            base_url: str = DEFAULT_LLM_URL, 
            api_key: NotGivenOr[str] = NOT_GIVEN, 
            generation_config:  dict,
            client: httpx.AsyncClient | None 
        ):
        addisai_api_key = api_key if is_given(api_key) else os.environ.get("ADDISAI_API_KEY")
        if not addisai_api_key:
            raise ValueError(
                "AddisAI API key is required, either as argument or set "
                "ADDISAI_API_KEY environment variable"
            )
        
        self._opts = LLMOptions(
            api_key= addisai_api_key,
            language=ADDIS_AI_LLM_LANGUAGES(language),
            base_url=base_url,
            **generation_config
        )

        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()
         
    
    @property
    def model(self) -> str:
        return "Addis-፩-አሌፍ"

    @property
    def provider(self) -> str:
        return "AddisAI"
    



    def chat(
        self,
        *,
        chat_ctx: ChatContext,
        tools: list[Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> "LLMStream":
        return LLMStream(
            llm=self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )

    async def aclose(self):
        if self._owns_client:
            await self._client.aclose()


class LLMStream(BaseLLMStream):
    def __init__(
        self,
        llm: LLM,
        *,
        chat_ctx: ChatContext,
        tools: list[Tool],
        conn_options: APIConnectOptions,
    ):
        super().__init__(
            llm=llm, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options
        )

    async def _run(self) -> None:
        llm: LLM = self._llm  # type: ignore
        opts = llm._opts
        chat_ctx = self._chat_ctx

        conversation_history = []
        for item in chat_ctx.items[:-1]:
            role = "assistant" if item.role == "assistant" else "user"
            content = item.text_content if hasattr(item, "text_content") else str(item)
            conversation_history.append({
                "role": role,
                "content": content,
            })

        if not chat_ctx.items:
            raise ValueError("chat_ctx must have at least one item")

        last_item = chat_ctx.items[-1]
        prompt = last_item.text_content if hasattr(last_item, "text_content") else str(last_item)

        generation_config = {}
        if opts.temperature is not None:
            generation_config["temperature"] = opts.temperature
        if opts.max_output_tokens is not None:
            generation_config["maxOutputTokens"] = opts.max_output_tokens
        if opts.top_p is not None:
            generation_config["topP"] = opts.top_p
        if opts.top_k is not None:
            generation_config["topK"] = opts.top_k

        data = {
            "prompt": prompt,
            "target_language": opts.language.value,
        }

        if conversation_history:
            data["conversation_history"] = conversation_history

        if generation_config:
            data["generation_config"] = generation_config

        headers = {
            "X-API-Key": opts.api_key,
            "Content-Type": "application/json",
        }

        logger.info(
            "llm_request",
            extra={
                "provider": llm.provider,
                "model": llm.model,
                "timeout": self._conn_options.timeout
            }
        )

        try:
            response = await llm._client.post(
                opts.base_url,
                json=data,
                headers=headers,
                timeout=self._conn_options.timeout
            )
            response.raise_for_status()

            logger.info(
                "llm_response_received",
                extra={
                    "provider": llm.provider,
                    "model": llm.model,
                    "status": response.status_code,
                },
            )
            
            response_data = response.json()
            content = response_data.get("response_text", "")
            
            usage_metadata = response_data.get("usage_metadata", {})
            from livekit.agents.llm import CompletionUsage
            usage = CompletionUsage(
                completion_tokens=usage_metadata.get("candidates_token_count", 0),
                prompt_tokens=usage_metadata.get("prompt_token_count", 0),
                total_tokens=usage_metadata.get("total_token_count", 0),
            ) if usage_metadata else None

            request_id = httpx.utils.to_bytes(os.urandom(8)).hex()
            
            self._event_ch.send_nowait(
                ChatChunk(
                    id=request_id,
                    delta=ChoiceDelta(
                        role=ChatRole.ASSISTANT,
                        content=content,
                    ),
                    usage=usage,
                )
            )
            
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
            logger.warning(
                "llm_network_error",
                extra={
                    "provider": llm.provider,
                    "model": llm.model,
                },
                exc_info=e,
            )
            raise APIError("Network error contacting LLM provider") from e