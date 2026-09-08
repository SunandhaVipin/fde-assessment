from task4.providers import (
    ModelProvider,
    ProviderFailure,
    ProviderRateLimited,
    ProviderTimeout,
)


class AllProvidersFailed(Exception):
    """Raised when the gateway cannot produce a completion."""
    pass


class CompletionRouter:
    def __init__(
        self,
        primary: ModelProvider,
        secondary: ModelProvider,
    ) -> None:
        self.primary = primary
        self.secondary = secondary

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
    ) -> dict:
        """
        Route a completion request.

        Routing policy:
        1. Always try primary first.
        2. Primary success -> return immediately.
        3. Primary HTTP 429 -> fall back to secondary.
        4. Primary timeout -> fall back to secondary.
        5. Other primary failures -> fail without fallback.
        """

        try:
            return await self.primary.complete(
                prompt=prompt,
                max_tokens=max_tokens,
            )

        except (ProviderRateLimited, ProviderTimeout):
            # These are the two explicitly permitted
            # fallback conditions.
            pass

        except ProviderFailure as exc:
            # Generic provider failures should not expose
            # upstream implementation details.
            raise AllProvidersFailed(
                "Primary provider failed"
            ) from exc

        try:
            return await self.secondary.complete(
                prompt=prompt,
                max_tokens=max_tokens,
            )

        except (
            ProviderRateLimited,
            ProviderTimeout,
            ProviderFailure,
        ) as exc:
            raise AllProvidersFailed(
                "No provider available"
            ) from exc