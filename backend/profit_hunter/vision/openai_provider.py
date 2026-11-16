"""OpenAI adapter (Responses API, official Python SDK).

Checked against the official documentation on 2026-11-16:
- ``client.responses.parse(..., text_format=PydanticModel)`` and ``response.output_parsed``
- images as ``{"type": "input_image", "image_url": "data:image/jpeg;base64,..."}``
- truncation: ``response.status == "incomplete"``; refusal: a content part of type "refusal"
The request carries NO tools: the model cannot browse, search, run code or act.
The SDK's own retries are switched off (``max_retries=0``) so every attempt
is one that the cost ledger has reserved.
"""

from __future__ import annotations

import base64
import os

from .provider import (EMPTY, INVALID, OK, REFUSED, TRUNCATED, ProviderError, ProviderResult, Usage,
                       VisionRequest)
from .schema import IdentificationOutput

API_KEY_ENV = "OPENAI_API_KEY"


class NotConfigured(Exception):
    """Live identification cannot run as configured. Never charged."""


def api_key_present() -> bool:
    return bool(os.environ.get(API_KEY_ENV, "").strip())


class OpenAIProvider:
    name = "openai"
    bills = True

    def __init__(self, client=None):
        if client is None:
            if not api_key_present():
                raise NotConfigured(f"No API key found. Set the {API_KEY_ENV} environment variable on the server.")
            from openai import OpenAI
            client = OpenAI(max_retries=0)  # reads the key from the environment; never logged
        self._client = client

    def identify(self, request: VisionRequest) -> ProviderResult:
        import openai

        content = [{"type": "input_text", "text": request.user_text}]
        for image in request.images:
            content.append({"type": "input_image", "detail": "high",
                            "image_url": "data:image/jpeg;base64," + base64.b64encode(image.data).decode("ascii")})
        try:
            response = self._client.responses.parse(
                model=request.model, instructions=request.instructions,
                input=[{"role": "user", "content": content}],
                text_format=IdentificationOutput,
                reasoning={"effort": request.reasoning_effort},
                max_output_tokens=request.max_output_tokens,
                store=False, timeout=request.timeout_seconds)
        except openai.APITimeoutError as exc:
            raise ProviderError("The request timed out. It may still have been processed and billed.",
                                transient=True, may_have_billed=True) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("The connection to OpenAI failed. The request may or may not have been received.",
                                transient=True, may_have_billed=True) from exc
        except (openai.RateLimitError, openai.InternalServerError) as exc:
            raise ProviderError(f"OpenAI is temporarily unavailable ({type(exc).__name__}). Nothing was billed.",
                                transient=True, may_have_billed=False) from exc
        except (openai.NotFoundError, openai.PermissionDeniedError) as exc:
            raise NotConfigured(
                f"The model '{request.model}' is not available to this API key. Check the model name in "
                f"Settings and your OpenAI account's access. No other model was tried.") from exc
        except openai.AuthenticationError as exc:
            raise NotConfigured("OpenAI rejected the API key.") from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"OpenAI rejected the request (HTTP {exc.status_code}). Nothing was billed.",
                                transient=False, may_have_billed=False) from exc
        except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError,
                openai.APIResponseValidationError) as exc:
            # The provider answered (and billed) but the SDK could not use the answer,
            # and no usage figures are available: the full reservation stays charged.
            return ProviderResult(INVALID, None, None, None, f"Unusable response ({type(exc).__name__}).")

        usage = None
        if response.usage is not None:
            details = getattr(response.usage, "output_tokens_details", None)
            usage = Usage(response.usage.input_tokens, response.usage.output_tokens,
                          getattr(details, "reasoning_tokens", None))
        model = response.model
        if response.status == "incomplete":
            reason = getattr(response.incomplete_details, "reason", None) or "unknown reason"
            return ProviderResult(TRUNCATED, None, usage, model, f"The response was cut off ({reason}).")
        for item in response.output:
            if item.type == "message":
                for part in item.content:
                    if part.type == "refusal":
                        return ProviderResult(REFUSED, None, usage, model, part.refusal)
        if response.status != "completed":
            return ProviderResult(INVALID, None, usage, model, f"Unexpected response status '{response.status}'.")
        parsed = response.output_parsed
        if parsed is None:
            return ProviderResult(EMPTY, None, usage, model, "The response contained no structured answer.")
        if not isinstance(parsed, IdentificationOutput):
            return ProviderResult(INVALID, None, usage, model, "The answer did not match the required structure.")
        return ProviderResult(OK, parsed, usage, model)
