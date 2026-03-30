import os
import httpx
from dataclasses import dataclass
from typing import Optional
from livekit.agents import tts
from livekit.agents.tts import ChunkedStream
from livekit.agents.utils import is_given
from livekit.agents.types import NOT_GIVEN, NotGivenOr, APIConnectOptions
from .types import addisaiTtsLanguages

@dataclass(frozen=True)
class TTSOptions:
    api_key: str
    language: addisaiTtsLanguages
    base_url: str = "https://api.addisassistant.com/api/v1/audio"
    stream: bool


class TTS(tts.TTS):
    def __init__(
        self,
        *,
        language: addisaiTtsLanguages,
        base_url: str = "https://api.addisassistant.com/api/v1/audio",
        api_key: NotGivenOr[str] = NOT_GIVEN,
        stream: bool = True,
    ):
        super().__init__(
            capabilities=tts.TTSCapabilities(
                streaming=True,
                aligned_transcript=False,
            )
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
        return AddisAIChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )
        

class AddisAIChunkedStream(ChunkedStream):
    async def _run(self) -> None:
        payload = {
            "text": self._input_text,
            "language": self._tts._opts.language,
            "stream": self._tts._opts.stream
        }

        headers = {
            "X-API-Key": self._tts._opts.api_key,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self._conn_options.timeout) as client:
                if self._tts._opts.stream:
                    async with client.stream(
                        "POST",
                        self._tts._opts.base_url,
                        json=payload,
                        headers=headers,
                    ) as response:
                        async for chunk in response.aiter_bytes():
                            if chunk:
                                self.push_audio(chunk)
                else:
                    response = await client.post(
                        self._tts._opts.base_url,
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()
                    self.push_audio(response.content)
            self.end()

        except Exception as e:
            self.error(e)


