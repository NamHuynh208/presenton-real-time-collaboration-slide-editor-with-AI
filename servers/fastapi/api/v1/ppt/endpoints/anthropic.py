from typing import Annotated, List
from fastapi import APIRouter, Body

from utils.provider_errors import normalize_provider_error
from utils.get_env import get_anthropic_api_key_env

from utils.available_models import (
    list_available_anthropic_models,
)

ANTHROPIC_ROUTER = APIRouter(prefix="/anthropic", tags=["Anthropic"])


@ANTHROPIC_ROUTER.post("/models/available", response_model=List[str])
async def get_available_models(
    api_key: Annotated[str, Body(embed=True)],
):
    try:
        return await list_available_anthropic_models(
            get_anthropic_api_key_env() if api_key == "oauth" else api_key
        )
    except Exception as e:
        raise normalize_provider_error(e, provider="Anthropic") from e
