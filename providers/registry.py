from providers.claude import ClaudeProvider
from providers.cursor import CursorProvider
from providers.gemini import GeminiProvider
from providers.gpt import GptProvider


PROVIDERS = {
    "claude": ClaudeProvider(),
    "cursor": CursorProvider(),
    "gpt": GptProvider(),
    "gemini": GeminiProvider(),
}


def get_provider(provider_id: str):
    try:
        return PROVIDERS[provider_id]
    except KeyError as error:
        raise KeyError(f"Unknown provider: {provider_id}") from error
