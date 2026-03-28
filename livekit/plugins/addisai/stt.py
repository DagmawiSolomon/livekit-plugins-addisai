import asyncio
from livekit.agents import stt

from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer, is_given


addisaiSttLanguages = Literal["am", "om"]

@dataclass
class STTOptions:
    language: addisaiSttLanguages
   

class STT(stt.STT):
    def __init__(
        self,
        *, 
        language:addisaiSttLanguages,
        base_url:str = "https://api.addisassistant.com/api/v2/stt",
        api_key:str | None = None
        ):

        addisai_api_key = api_key if is_given(api_key) else os.environ.get("ADDISAI_API_KEY")
        if not addisai_api_key:
            raise ValueError(
                "AddisAI API key is required, either as argument or set"
                "ADDISAI_API_KEY environment variable"
            )

        if(is_given(language)):
            self._language = language
        else:
            self._language = "am"
       

    def model(self) -> str:
        return "Unkown"
    
    def provider(self) -> str:
        return "AddisAI"
    
    def update_options(self, *, language:NotGivenOr[str] = NOT_GIVEN) -> None:
        if is_given(language):
            self._language = language

    def stream(self):
        pass