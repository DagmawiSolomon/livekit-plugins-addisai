
import logging


from livekit.agents import llm
from livekit.agents.types import APIConnectOptions, NOT_GIVEN, NotGivenOr, 
from livekit.agents.chat_context import ChatContext,

from .constants import API_BASE_URL

DEFAULT_LLM_URL = f"{API_BASE_URL}/v1/chat_generate"
ADDIS_AI_STT_LANGUAGES = Literal["am", "om"]

logger = logging.getLogger(__name__)




class llm(llm.LLM):
    def __ini__():
        pass

    
    @property
    def model(self) -> str:
        return "Addis-፩-አሌፍ"

    @property
    def provider(self) -> str:
        return "AddisAI"

    def chat(
        self,
        *,
        chat_ctx: ChatContext,
        tools: list[Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> LLMStream:
        pass