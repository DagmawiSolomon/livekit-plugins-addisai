import asyncio
import os
import random
import json
import logging
from dataclasses import dataclass, replace


import httpx
from typing import Literal

from livekit.agents import stt
from livekit.agents.stt import SpeechData, SpeechEvent, SpeechEventType
from livekit.agents.types import APIConnectOptions, NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer, is_given
from livekit.agents._exceptions import APIError
from .constants import API_BASE_URL




DEFAULT_STT_URL = f"{API_BASE_URL}/api/v2/stt"   
ADDIS_AI_STT_LANGUAGES = Literal["am", "om"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class STTOptions:
    api_key: str
    language: ADDIS_AI_STT_LANGUAGES
    base_url: str = DEFAULT_STT_URL

class STT(stt.STT):
    def __init__(
        self,
        *, 
        language: ADDIS_AI_STT_LANGUAGES,
        base_url:str = DEFAULT_STT_URL,
        api_key:NotGivenOr[str] = NOT_GIVEN
        ):

        super().__init__(
            capabilities=stt.STTCapabilities(
                streaming=False,
                interim_results=False, 
                offline_recognize=True
            )
        )

        addisai_api_key = api_key if is_given(api_key) else os.environ.get("ADDISAI_API_KEY")
        if not addisai_api_key:
            raise ValueError(
                "AddisAI API key is required, either as argument or set "
                "ADDISAI_API_KEY environment variable"
            )

        self._opts = STTOptions(
            api_key=addisai_api_key,
            language=language,
            base_url=base_url
        )

        self._client = httpx.AsyncClient()
    @property
    def model(self) -> str:
        return "Unknown"
    @property
    def provider(self) -> str:
        return "AddisAI"

    def update_options(self, *, language:NotGivenOr[str] = NOT_GIVEN) -> None:
        if is_given(language):
            self._opts = replace(self._opts, language=language)

    
    async def post(self, url, files, data, conn_options):
        headers = {"X-API-Key": self._opts.api_key}

        logger.info(
            "stt_request",
            extra={
                "provider": self.provider,
                "model": self.model,
                "timeout": conn_options.timeout,
            },
        )

        try:
            response = await self._client.post(
                url,
                headers=headers,
                files=files,
                data=data,
                timeout=conn_options.timeout,
            )

            logger.info(
                "stt_response_received",
                extra={
                    "provider": self.provider,
                    "model": self.model,
                    "status": response.status_code,
                },
            )

            return response

        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
            logger.warning(
                "stt_network_error",
                extra={
                    "provider": self.provider,
                    "model": self.model,
                },
                exc_info=e,
            )
            raise APIError("Network error contacting STT provider") from e

    async def _recognize_impl(self,audio: AudioBuffer,*,language: NotGivenOr[ADDIS_AI_STT_LANGUAGES] = NOT_GIVEN,conn_options: APIConnectOptions) -> SpeechEvent:
        language = language if is_given(language) else self._opts.language
        wav_bytes = audio.to_wav_bytes()

        logger.info(
            "stt_recognition_started",
            extra={
                "provider": self.provider,
                "model": self.model,
                "language": str(language),
                "audio_bytes": len(wav_bytes),
            },
        )

        files = {"audio": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"language_code": str(language)}

        response = await self.post(
            self._opts.base_url,
            files,
            data,
            conn_options=conn_options,
        )

        status = response.status_code

        if status == 429 or 500 <= status < 600:
            logger.warning(
                "stt_http_error",
                extra={
                    "provider": self.provider,
                    "model": self.model,
                    "status": status,
                },
            )
            raise APIError(f"STT error {status}")

        if status >= 400:
            logger.error(
                "stt_http_error",
                extra={
                    "provider": self.provider,
                    "model": self.model,
                    "status": status,
                },
            )
            raise ValueError(f"STT error {status}")

        try:
            res = response.json()
        except Exception as e:
            logger.warning(
                "stt_invalid_response",
                extra={
                    "provider": self.provider,
                    "model": self.model,
                },
                exc_info=e,
            )
            raise ValueError("Invalid JSON from STT provider") from e

        transcript = res.get("data", {}).get("transcription", "")

        logger.info(
            "stt_recognition_completed",
            extra={
                "provider": self.provider,
                "model": self.model,
                "language": str(language),
                "transcript_length": len(transcript),
            },
        )

        return SpeechEvent(
            type=SpeechEventType.FINAL_TRANSCRIPT,
            alternatives=[
                SpeechData(
                    text=transcript,
                    language=language,
                )
            ],
        )