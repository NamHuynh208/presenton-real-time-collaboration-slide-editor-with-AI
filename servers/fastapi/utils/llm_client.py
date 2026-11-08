from llmai import get_client as get_provider_client

from api.v1.auth.context import get_current_actor_id
from enums.llm_provider import LLMProvider
from utils.llm_provider import get_llm_provider


def get_client(*, config, logger=None):
    if get_llm_provider() == LLMProvider.CLAUDE_CODE:
        from fastapi import HTTPException
        from utils.claude_code_client import ClaudeCodeClient

        user_id = get_current_actor_id()
        if user_id is None:
            raise HTTPException(401, "Sign in to Presenton to use your Claude Code account.")
        return ClaudeCodeClient(user_id=user_id, generation_defaults=config.generation)
    return get_provider_client(config=config, logger=logger)
