from providers.claude import ClaudeProvider


# Cursor, GPT, and Gemini are registered in Task 6.
PROVIDERS = {
    "claude": ClaudeProvider(),
}


def get_provider(provider_id: str):
    try:
        return PROVIDERS[provider_id]
    except KeyError as error:
        raise KeyError(f"Unknown provider: {provider_id}") from error
