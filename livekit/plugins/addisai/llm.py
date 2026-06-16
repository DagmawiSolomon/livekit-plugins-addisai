

import os
import json
import logging
from typing import Any
from dataclasses import dataclass

import httpx

from enum import Enum
from livekit.agents import llm
from livekit.agents.llm import ChatContext, LLMStream, Tool, ToolChoice
from livekit.agents.types import APIConnectOptions, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import is_given
from livekit.agents._exceptions import APIError

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
    
    async def _send_llm_request(self,*,url,data,conn_options) -> httpx.Response:    
        headers = {
            "X-API-Key": self._opts.api_key,
            "Content-Type": "application/json",
        }
        logger.info(
            "llm_request",
            extra={
                "provider": self.provider,
                "model": self.model,
                "timeout": conn_options.timeout
            }
        )

        try: 
            response = await self._client.post(
                url,
                json=data,
                headers=headers,
                timeout=conn_options.timeout
            )

            logger.info(
                "llm_response_received",
                extra={
                    "provider": self.provider,
                    "model": self.model,
                    "status": response.status_code,
                },
            )

            return response
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
            logger.warning(
                "llm_network_error",
                extra={
                    "provider": self.provider,
                    "model": self.model,
                },
                exc_info=e,
            )
            raise APIError("Network error contacting LLM provider") from e




    async def chat(
        self,
        *,
        chat_ctx: ChatContext,
        tools: list[Tool] | None = None,
        conn_options: APIConnectOptions ,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> LLMStream:
        
        try:
            
            conversation_history = []
            for item in chat_ctx.items[:-1]:
                role = "assistant" if item.role == "assistant" else "user"
                content = item.text_content if hasattr(item, "text_content") else str(item)
                conversation_history.append({
                    "role": role,
                    "content": content,
                })

            last_item = chat_ctx.items[-1]
            prompt = last_item.text_content if hasattr(last_item, "text_content") else str(last_item)

            generation_config = {}
            if self._opts.temperature is not None:
                generation_config["temperature"] = self._opts.temperature
            if self._opts.max_output_tokens is not None:
                generation_config["maxOutputTokens"] = self._opts.max_output_tokens
            if self._opts.top_p is not None:
                generation_config["topP"] = self._opts.top_p
            if self._opts.top_k is not None:
                generation_config["topK"] = self._opts.top_k

            data = {
                "prompt": prompt,
                "target_language": self._opts.language.value,
            }

            if conversation_history:
                data["conversation_history"] = conversation_history

            if generation_config:
                data["generation_config"] = generation_config

            response = await self._send_llm_request(
                url=self._opts.base_url,
                data=data,
                conn_options=conn_options,
            )

            #create an llm stream from the data
        except:
            pass

    async def aclose(self):
        if self._owns_client:
            await self._client.aclose()