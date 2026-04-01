import os
import base64
import json
import httpx
import io
import wave
from dataclasses import dataclass, replace
from typing import Optional, AsyncIterator
from livekit.agents import tts, utils
from livekit.agents.tts import ChunkedStream, AudioEmitter
from livekit.agents.utils.audio import AudioByteStream
from livekit.agents.utils import is_given
from livekit.agents.types import NOT_GIVEN, NotGivenOr, APIConnectOptions, DEFAULT_API_CONNECT_OPTIONS
from .types import addisaiTtsLanguages
from livekit import rtc


@dataclass()
class TTSOptions:
    sample_rate: int
    api_key: str
    language: addisaiTtsLanguages
    stream: bool = False
    base_url: str = "https://api.addisassistant.com/api/v1/audio"


class TTS(tts.TTS):
    def __init__(
        self,
        *,
        language: addisaiTtsLanguages,
        base_url: str = "https://api.addisassistant.com/api/v1/audio",
        api_key: NotGivenOr[str] = NOT_GIVEN,
        stream: bool = False,
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
            # text=text,
            sample_rate=sample_rate,
            stream=stream
        )

        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def model(self) -> str:
        return "አሌፍ-Audio"
    
    @property
    def provider(self) -> str:
        return "AddisAI"

    def update_options(self, *, stream: Optional[bool] = None) -> None:
        if is_given(stream):
            self._opts.stream = stream
        
    
    def synthesize(self, text: str, *, conn_options: APIConnectOptions = APIConnectOptions(max_retry=3, retry_interval=2.0, timeout=10.0)) -> ChunkedStream:
        return ChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )

    def stream(self,*,conn_options: APIConnectOptions,) -> ChunkedStream:
        return ChunkedStream(
            tts=self,
            input_text="",
            conn_options=conn_options,
        )


class ChunkedStream(ChunkedStream):

    def __init__(self,*,tts:TTS, input_text:str, conn_options:APIConnectOptions=DEFAULT_API_CONNECT_OPTIONS) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts = tts
        self._opts= replace(tts._opts)
        

    async def _run(self, output_emitter:AudioEmitter) -> None:
        payload = {
            "text": self._input_text,
            "language": self._tts._opts.language,
            "stream": True,
         }

        headers = {
            "X-API-Key": self._tts._opts.api_key,
            "Content-Type": "application/json",
        }

        print("Running...")

        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._opts.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )

        async with httpx.AsyncClient(timeout=self._conn_options.timeout) as client:
            async with client.stream(
                "POST",
                self._tts._opts.base_url,
                json=payload,
                headers=headers,
            ) as response:
                print("Inside")
                response.raise_for_status()
                audio_stream = AudioByteStream(
                    sample_rate=self._tts.sample_rate,
                    num_channels=self._tts.num_channels,
                )

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    data = json.loads(line)
                    b64 = data.get("audio_chunk")
                    if not b64:
                        continue

                    wav_bytes = base64.b64decode(b64)

                    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                        raw_pcm = wf.readframes(wf.getnframes())

                        self._tts.sample_rate = wf.getframerate()
                        self._tts.num_channels = wf.getnchannels()

                    for frame in audio_stream.write(raw_pcm):
                        output_emitter.push(frame)

            for frame in audio_stream.flush():
                output_emitter.push(frame)

            output_emitter.flush()


                    


