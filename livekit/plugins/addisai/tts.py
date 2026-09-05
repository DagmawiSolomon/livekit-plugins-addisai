import asyncio
import base64
import binascii
import logging
import os
from dataclasses import dataclass, replace

from enum import Enum
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

class ADDIS_AI_TTS_LANGUAGES(str, Enum):
    AM = "am"
    OM = "om"


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TTSOptions:
    api_key: str
    language: ADDIS_AI_TTS_LANGUAGES
    base_url: str = DEFAULT_TTS_URL
    sample_rate: int = 16000


class TTS(tts.TTS):
    def __init__(
        self,
        *,
        language=ADDIS_AI_TTS_LANGUAGES,
        base_url: str = DEFAULT_TTS_URL,
        api_key: NotGivenOr[str] = NOT_GIVEN,
        sample_rate: int = 16000,
        num_channels: int = 1,
        client: httpx.AsyncClient = None,
    ):
        super().__init__(
            capabilities=tts.TTSCapabilities(
                streaming=False,
                aligned_transcript=False,
            ),
            sample_rate=sample_rate,
            num_channels=num_channels,
        )

        addisai_api_key = api_key if is_given(api_key) else os.environ.get("ADDISAI_API_KEY")
        if not addisai_api_key:
            raise ValueError(
                "AddisAI API key is required, either as argument or set "
                "ADDISAI_API_KEY environment variable"
            )

        self._opts = TTSOptions(
            api_key=addisai_api_key,
            language=ADDIS_AI_TTS_LANGUAGES(language),
            base_url=base_url,
            sample_rate=sample_rate,
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()

    @property
    def model(self) -> str:
        return "አሌፍ-Audio"

    @property
    def provider(self) -> str:
        return "AddisAI"

    def update_options(self, *, language: NotGivenOr[str] = NOT_GIVEN) -> None:
        if is_given(language):
            self._opts = replace(self._opts, language=language)

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = APIConnectOptions(
            max_retry=3, retry_interval=2.0, timeout=30.0
        ),
    ) -> BaseChunkedStream:
        return ChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class AudioDecodeError(Exception):
    """Raised when audio data cannot be decoded into PCM."""


class ChunkedStream(BaseChunkedStream):

    def __init__(
        self,
        *,
        tts: TTS,
        input_text: str,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts = tts
        self._opts = replace(tts._opts)

    def _wav_bytes_to_pcm(self, wav_bytes: bytes) -> bytes:
        """Decode raw WAV bytes to 16-bit signed PCM at the configured sample rate."""
        try:
            decoded = miniaudio.decode(
                wav_bytes,
                output_format=miniaudio.SampleFormat.SIGNED16,
                nchannels=1,
                sample_rate=self._tts._opts.sample_rate,
            )
            return bytes(decoded.samples)
        except miniaudio.DecodeError as e:
            raise AudioDecodeError("Failed to decode WAV audio") from e

    def _base64_to_pcm(self, b64_str: str) -> bytes:
        """Decode a base64-encoded WAV string to PCM."""
        try:
            wav_bytes = base64.b64decode(b64_str)
        except binascii.Error as e:
            raise AudioDecodeError("Invalid base64 audio data") from e
        return self._wav_bytes_to_pcm(wav_bytes)

    def _build_request(self):
        lang = (
            self._tts._opts.language.value
            if hasattr(self._tts._opts.language, "value")
            else str(self._tts._opts.language)
        )
        return (
            {
                "text": self._input_text,
                "language": lang,
                "stream": False,  # Always use non-streaming: returns {"audio": "<base64 WAV>"}
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
                extra={"provider": self._tts.provider, "model": self._tts.model, "status": status},
            )
            raise ValueError(f"TTS rate limited {status}")

        if 500 <= status < 600:
            logger.warning(
                "tts_http_error",
                extra={"provider": self._tts.provider, "model": self._tts.model, "status": status},
            )
            raise APIError(f"TTS error {status}")

        if status >= 400:
            logger.error(
                "tts_http_error",
                extra={
                    "provider": self._tts.provider,
                    "model": self._tts.model,
                    "status": status,
                    "body": response.text,
                },
            )
            raise ValueError(f"TTS error {status}: {response.text}")

    async def _run(self, output_emitter: AudioEmitter) -> None:
        payload, headers = self._build_request()

        logger.info(
            "tts_synthesis_started",
            extra={
                "provider": self._tts.provider,
                "model": self._tts.model,
                "language": payload["language"],
                "text_length": len(self._input_text),
            },
        )

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._tts._opts.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )

        try:
            response = await self._tts._client.post(
                self._tts._opts.base_url,
                json=payload,
                headers=headers,
                timeout=self._conn_options.timeout,
            )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as e:
            logger.warning(
                "tts_network_error",
                extra={"provider": self._tts.provider, "model": self._tts.model},
                exc_info=e,
            )
            raise APIError("Network error contacting TTS provider") from e

        self._check_status(response)

        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            # Non-streaming: {"audio": "<base64 WAV>"}
            try:
                data = response.json()
            except Exception as e:
                raise ValueError("Invalid JSON from TTS provider") from e

            b64 = data.get("audio")
            if not b64:
                raise ValueError(f"No 'audio' field in TTS response: {list(data.keys())}")

            pcm = self._base64_to_pcm(b64)
            output_emitter.push(pcm)

        elif "audio" in content_type:
            # Raw WAV bytes
            pcm = self._wav_bytes_to_pcm(response.content)
            output_emitter.push(pcm)

        else:
            # Try JSON first, then raw bytes
            try:
                data = response.json()
                b64 = data.get("audio") or data.get("audio_chunk")
                if b64:
                    output_emitter.push(self._base64_to_pcm(b64))
                else:
                    raise ValueError(f"Unknown TTS response format: {list(data.keys())}")
            except Exception:
                pcm = self._wav_bytes_to_pcm(response.content)
                output_emitter.push(pcm)

        logger.info(
            "tts_synthesis_completed",
            extra={
                "provider": self._tts.provider,
                "model": self._tts.model,
                "language": payload["language"],
                "text_length": len(self._input_text),
            },
        )

        output_emitter.flush()
