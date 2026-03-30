import os
from typing import Literal
from dataclasses import dataclass

import httpx
import asyncio


from livekit.agents import stt
from livekit.agents.utils import AudioBuffer
from livekit.agents.types import APIConnectOptions
from livekit.agents.stt import SpeechEvent, SpeechEventType, SpeechData

from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer, is_given

from types import addisaiSttLanguages

@dataclass(frozen=True)
class STTOptions:
    api_key: str
    language: addisaiSttLanguages
    base_url: str = "https://api.addisassistant.com/api/v2/stt"
   

class STT(stt.STT):
    def __init__(
        self,
        *, 
        language:addisaiSttLanguages,
        base_url:str = "https://api.addisassistant.com/api/v2/stt",
        api_key:str | None = None
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


       
    @property
    def model(self) -> str:
        return "Unkown"
    @property
    def provider(self) -> str:
        return "AddisAI"
    
    def update_options(self, *, language:NotGivenOr[str] = NOT_GIVEN) -> None:
        if is_given(language):
            self._language = language


    async def post(self, url,files,data):
        headers = {
            "Authorization": self._opts.api_key
        }
        response = await self._client.post(
            url,
            headers=headers,
            files=files,
            data=data
        )
        return response.json()


    async def _recognize_impl(self,audio:AudioBuffer,*,language: NotGivenOr[addisaiSttLanguages] = NOT_GIVEN,conn_options:APIConnectOptions) -> SpeechEvent:
        wav_bytes = audio.to_wav_bytes()
        language = language if is_given(language) else self._opts.language
        files = {
            "file": ("audio.wav", wav_bytes, "audio/wav")
        }
        data = {
            "language": str(language)
        }

        result = await self.post(self._opts.base_url,files,data)
        transcript = result.get("data").get("transcription")
        return SpeechEvent(
                type=SpeechEventType.FINAL_TRANSCRIPT,
                alternatives=[
                    SpeechData(
                        text=transcript,
                        language=language,
                    )
                ],
            )
        





