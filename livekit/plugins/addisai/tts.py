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
from .types import addisaiTtsLanguages


@dataclass()
class TTSOptions:
    api_key: str
    language: addisaiTtsLanguages
    stream: bool = True
    base_url: str = "https://api.addisassistant.com/api/v1/audio"
    sample_rate: int = 24000


class TTS(tts.TTS):
    def __init__(
        self,
        *,
        language: addisaiTtsLanguages,
        base_url: str = "https://api.addisassistant.com/api/v1/audio",
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

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )

    @property
    def model(self) -> str:
        return "አሌፍ-Audio"

    @property
    def provider(self) -> str:
        return "AddisAI"

    async def aclose(self) -> None:
        await self._client.aclose()

    def update_options(self, *, stream: Optional[bool] = None) -> None:
        if is_given(stream):
            self._opts.stream = stream

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
        """Decode a Base64-encoded audio chunk to raw 16-bit signed little-endian PCM.

        The AddisAI API returns MP3 chunks in streaming mode and WAV in non-streaming
        mode. miniaudio handles both formats transparently without any system
        dependencies (no ffmpeg). It also resamples to the configured sample rate
        and downmixes to mono in a single C-level pass — no extra allocations.
        """
        audio_bytes = base64.b64decode(api_base64_audio)
        decoded = miniaudio.decode(
            audio_bytes,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=self._tts._opts.sample_rate,
        )
        return bytes(decoded.samples)

    async def _run(self, output_emitter: AudioEmitter) -> None:
        payload = {
            "text": self._input_text,
            "language": self._tts._opts.language,
            "stream": self._tts._opts.stream,
        }

        headers = {
            "X-API-Key": self._tts._opts.api_key,
            "Content-Type": "application/json",
        }

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._tts._opts.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )

        client = self._tts._client

        if self._tts._opts.stream:
            async with client.stream(
                "POST",
                self._tts._opts.base_url,
                json=payload,
                headers=headers,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    base64_str = data.get("audio_chunk")
                    if not base64_str:
                        continue
                    pcm_data = self.decode_to_pcm(base64_str)
                    output_emitter.push(pcm_data)
        else:
            response = await client.post(
                self._tts._opts.base_url,
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            data = response.json()
            base64_str = data.get("audio")
            if base64_str:
                pcm_data = self.decode_to_pcm(base64_str)
                output_emitter.push(pcm_data)

        output_emitter.flush()