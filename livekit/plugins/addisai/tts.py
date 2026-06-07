import asyncio
import base64
import binascii
import json
import logging
import os
from dataclasses import dataclass, replace
from typing import Literal, Optional

import httpx
import miniaudio
from livekit.agents import tts, utils
from livekit.agents._exceptions import APIError
from livekit.agents.tts import AudioEmitter
from livekit.agents.tts import ChunkedStream as BaseChunkedStream
from livekit.agents.types import (
    APIConnectOptions,
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    NotGivenOr,
)
from livekit.agents.utils import is_given

from .constants import API_BASE_URL

DEFAULT_TTS_URL = f"{API_BASE_URL}/api/v1/audio"
ADDIS_AI_TTS_LANGUAGES = Literal["am","om"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TTSOptions:
    api_key: str
    language: ADDIS_AI_TTS_LANGUAGES
    stream: bool = True
    base_url: str = DEFAULT_TTS_URL
    sample_rate: int = 24000


class TTS(tts.TTS):
    def __init__(
        self,
        *,
        language: ADDIS_AI_TTS_LANGUAGES,
        base_url: str = DEFAULT_TTS_URL,
        api_key: NotGivenOr[str] = NOT_GIVEN,
        stream: bool = True,
        sample_rate: int = 24000,
        num_channels: int = 1
    ):
        super().__init__(
            capabilities=tts.TTSCapabilities(
                streaming=False,
                aligned_transcript=False,
            ),
            sample_rate=sample_rate,
            num_channels=num_channels
        )

        addisai_api_key = api_key if is_given(api_key) else os.environ.get("ADDISAI_API_KEY")
        if not addisai_api_key:
            raise ValueError(
                "AddisAI API key is required, either as argument or set "
                "ADDISAI_API_KEY environment variable"
            )

        self._opts = TTSOptions(
            api_key=addisai_api_key,
            language=language,
            base_url=base_url,
            sample_rate=sample_rate,
            stream=stream
        )

        self._client = httpx.AsyncClient()

    @property
    def model(self) -> str:
        return "አሌፍ-Audio"

    @property
    def provider(self) -> str:
        return "AddisAI"

    async def aclose(self) -> None:
        await self._client.aclose()

    def update_options(self, *, language:NotGivenOr[str] = NOT_GIVEN) -> None:
        if is_given(language):
            self._opts = replace(self._opts, language=language)


    def synthesize(self, text: str, *, conn_options: APIConnectOptions = APIConnectOptions(max_retry=3, retry_interval=2.0, timeout=10.0)) -> BaseChunkedStream:
        return ChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )

class AudioDecodeError(Exception):
    """Raised when audio data cannot be decoded into PCM."""

class ChunkedStream(BaseChunkedStream):

    def __init__(self, *, tts: TTS, input_text: str, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts = tts
        self._opts = replace(tts._opts)

    def decode_to_pcm(self, api_base64_audio: str) -> bytes:
        try:
            audio_bytes = base64.b64decode(api_base64_audio)
            decoded = miniaudio.decode(
                audio_bytes,
                output_format=miniaudio.SampleFormat.SIGNED16,
                nchannels=1,
                sample_rate=self._tts._opts.sample_rate,
            )
            return bytes(decoded.samples)
        except binascii.Error as e:
            raise AudioDecodeError("Invalid base64 audio data") from e
        except miniaudio.DecodeError as e:
            raise AudioDecodeError("Failed to decode audio data") from e
            

    
    def _build_request(self):
        return (
            {
                "text": self._input_text,
                "language": self._tts._opts.language,
                "stream": self._tts._opts.stream,
            },
            {
                "X-API-Key": self._tts._opts.api_key,
                "Content-Type": "application/json",
            },
        )

    def _check_status(self, response):
        status = response.status_code

        if status == 429:
            logger.warning(
                "tts_rate_limited",
                extra={
                    "provider": self._tts.provider,
                    "model": self._tts.model,
                    "status": status,
                }
            )
            raise ValueError(f"TTS rate limited {status}")

        if 500 <= status < 600:
            logger.warning(
                "tts_http_error",
                extra={
                    "provider": self._tts.provider,
                    "model": self._tts.model,
                    "status": status,
                },
            )
            raise APIError(f"TTS error {status}")

        if status >= 400:
            logger.error(
                "tts_http_error",
                extra={
                    "provider": self._tts.provider,
                    "model": self._tts.model,
                    "status": status,
                },
            )
            raise ValueError(f"TTS error {status}")

    def _parse_stream_line(self, line: str):
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning(
                "tts_invalid_stream_line",
                extra={
                    "provider": self._tts.provider,
                    "model": self._tts.model,
                },
                exc_info=e,
            )
            return None

        base64_str = data.get("audio_chunk")
        if not base64_str:
            return None

        return self.decode_to_pcm(base64_str)


    async def _run_streaming(self, output_emitter: AudioEmitter):
        payload, headers = self._build_request() 
        
        logger.info(
            "tts_stream_request",
            extra={
                "provider": self._tts.provider,
                "model": self._tts.model,
                "timeout": self._conn_options.timeout,
            },
        )

        try:
            async with self._tts._client.stream(
                "POST",
                self._tts._opts.base_url,
                json=payload,
                headers=headers,
                timeout=self._conn_options.timeout,
            ) as response:
    
                self._check_status(response)
                
                logger.info(
                    "tts_stream_response_received",
                    extra={
                        "provider": self._tts.provider,
                        "model": self._tts.model,
                        "status": response.status_code,
                    },
                )
    
                async for line in response.aiter_lines():
                        if not line:
                            continue
                        pcm = self._parse_stream_line(line)
                        if pcm:
                            output_emitter.push(pcm)

        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
            logger.warning(
                "tts_network_error",
                extra={
                    "provider": self._tts.provider,
                    "model": self._tts.model,
                },
                exc_info=e,
            )
            raise APIError("Network error contacting TTS provider") from e

    async def _run_non_streaming(self, output_emitter):
        payload, headers = self._build_request()

        logger.info(
            "tts_request",
            extra={
                "provider": self._tts.provider,
                "model": self._tts.model,
                "timeout": self._conn_options.timeout,
            },
        )

        try:
            response = await self._tts._client.post(
                self._tts._opts.base_url,
                json=payload,
                headers=headers,
                timeout=self._conn_options.timeout,
            )

            logger.info(
                "tts_response_received",
                extra={
                    "provider": self._tts.provider,
                    "model": self._tts.model,
                    "status": response.status_code,
                },
            )

        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
            logger.warning(
                "tts_network_error",
                extra={
                    "provider": self._tts.provider,
                    "model": self._tts.model,
                },
                exc_info=e,
            )
            raise APIError("Network error contacting TTS provider") from e

        self._check_status(response)

        try:
            data = response.json()
        except Exception as e:
            logger.warning(
                "tts_invalid_response",
                extra={
                    "provider": self._tts.provider,
                    "model": self._tts.model,
                },
                exc_info=e,
            )
            raise ValueError("Invalid JSON from TTS provider") from e
        base64_str = data.get("audio")

        if base64_str:
            output_emitter.push(self.decode_to_pcm(base64_str))



    async def _run(self, output_emitter: AudioEmitter) -> None:

        logger.info(
            "tts_synthesis_started",
            extra={
                "provider": self._tts.provider,
                "model": self._tts.model,
                "language": str(self._tts._opts.language),
                "text_length": len(self._input_text),
                "streaming": self._tts._opts.stream,
            },
        )

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._tts._opts.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )

        if self._tts._opts.stream:        
            await self._run_streaming(output_emitter)
        else:
            await self._run_non_streaming(output_emitter)
           
        logger.info(
            "tts_synthesis_completed",
            extra={
                "provider": self._tts.provider,
                "model": self._tts.model,
                "language": str(self._tts._opts.language),
                "text_length": len(self._input_text),
                "streaming": self._tts._opts.stream,
            },
        )

        output_emitter.flush()