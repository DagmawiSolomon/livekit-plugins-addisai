import logging
import asyncio
import os
import base64
import json
import httpx
import miniaudio
from dataclasses import dataclass, replace
from typing import Optional
from livekit.agents import tts, utils
from livekit.agents.tts import AudioEmitter
from livekit.agents.tts import ChunkedStream as BaseChunkedStream
from livekit.agents.utils import is_given
from livekit.agents.types import NOT_GIVEN, NotGivenOr, APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS
from typing import Literal

from .constants import API_BASE_URL

ADDIS_AI_TTS_LANGUAGES = Literal["am","om"]

logger = logging.getLogger(__name__)

DEFAULT_TTS_URL = f"{API_BASE_URL}/api/v1/audio"
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


class ChunkedStream(BaseChunkedStream):

    def __init__(self, *, tts: TTS, input_text: str, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts = tts
        self._opts = replace(tts._opts)

    def decode_to_pcm(self, api_base64_audio: str) -> bytes:
        audio_bytes = base64.b64decode(api_base64_audio)
        decoded = miniaudio.decode(
            audio_bytes,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=self._tts._opts.sample_rate,
        )
        return bytes(decoded.samples)

    
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

    def _raise_for_status(self, response):
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise APIError(
                f"STT provider error: {response.status_code}"
            ) from e

    def _parse_stream_line(self, line: str):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        base64_str = data.get("audio_chunk")
        if not base64_str:
            return None

        return self.decode_to_pcm(base64_str)


    async def _run_streaming(self, output_emitter: AudioEmitter):
        payload, headers = self._build_request() 
        async with self._tts._client.stream(
            "POST",
            self._tts._opts.base_url,
            json=payload,
            headers=headers,
            timeout=self._conn_options.timeout,
        ) as response:

            self._raise_for_status(response)
            async for line in response.aiter_lines():
                    if not line:
                        continue
                    pcm = self._parse_stream_line(line)
                    if pcm:
                        output_emitter.push(pcm)

    async def _run_non_streaming(self, output_emitter):
        payload, headers = self._build_request()

        response = await self._tts._client.post(
            self._tts._opts.base_url,
            json=payload,
            headers=headers,
            timeout=self._conn_options.timeout,
        )

        self._raise_for_status(response)

        data = response.json()
        base64_str = data.get("audio")

        if base64_str:
            output_emitter.push(self.decode_to_pcm(base64_str))



    async def _run(self, output_emitter: AudioEmitter) -> None:

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
           
        output_emitter.flush()