import os
from dataclasses import dataclass, replace
import random

import httpx
import asyncio


from livekit.agents import stt
from livekit.agents.utils import AudioBuffer
from livekit.agents.types import APIConnectOptions
from livekit.agents.stt import SpeechEvent, SpeechEventType, SpeechData

from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer, is_given
from typings import Literal
from livekit.plugins.addisai import API_BASE_URL


DEFAULT_STT_URL = f"{API_BASE_URL}/api/v2/stt"   
ADDIS_AI_STT_LANGUAGES = Literal["am", "om"]


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

        self._client = httpx.AsyncClient(timeout=30.0)
        self.MAX_RETRIES = 5
        self.attempts = 0
        self.delay = 1
    @property
    def model(self) -> str:
        return "Unkown"
    @property
    def provider(self) -> str:
        return "AddisAI"

    def update_options(self, *, language:NotGivenOr[str] = NOT_GIVEN) -> None:
        if is_given(language):
            return replace(self, language=langauge)
        return self

    async def post(self, url,files,data, attempt=0):
        headers = {
            "X-API-Key": self._opts.api_key
        }

        for attempt in range(self.MAX_RETRIES+1):
            try:    
                response = await self._client.post(
                    url,
                    headers=headers,
                    files=files,
                    data=data
                )
                retry_after = int(response.headers.get("Retry-After"))
                if response.status_code not in RETRIABLE_STATUS_CODES:
                    return response.json()
                if attempt == self.MAX_RETRIES:
                    response.raise_for_status()
                if retry_after:
                    delay = min(int(retry_after),10)
                else:    
                    delay = random.uniform(0,self.delay * (2 ** attempts))
                await asyncio.sleep(delay)
            except Exception as exec:
                if attempt == self.MAX_RETRIES:
                    respone.raise_for_status()
                delay = random.uniform(
                    0,
                    self.delay * (2**attempts)
                )
                await asyncio.sleep(delay)
    
    async def _recognize_impl(self,audio:AudioBuffer,*,language: NotGivenOr[addisaiSttLanguages] = NOT_GIVEN,conn_options:APIConnectOptions) -> SpeechEvent:
        wav_bytes = audio.to_wav_bytes()
        language = language if is_given(language) else self._opts.language
        files = {
            "audio": ("audio.wav", wav_bytes, "audio/wav")
        }
        data = {
            "language_code": str(language)
        }

        res = await self.post(self._opts.base_url,files,data)
        transcript = res.get("data", {}).get("transcription")
        return SpeechEvent(
                type=SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[
                    SpeechData(
                        text=transcript,
                        language=language,
                    )
                ],
            )
        





