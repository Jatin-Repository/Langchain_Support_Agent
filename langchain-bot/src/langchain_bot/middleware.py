from datetime import datetime

from langchain.agents.middleware import (
    wrap_model_call,
    wrap_tool_call,
)


def _ts():
    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


@wrap_model_call
def model_logging_middleware(request, handler):
    """
    Log model requests and responses.
    """

    messages = request.state.get(
        "messages",
        []
    )

    print(
        f"[{_ts()}] [MODEL] "
        f"message_count={len(messages)}"
    )

    if messages:
        last_message = messages[-1]

        content = getattr(
            last_message,
            "content",
            ""
        )

        if isinstance(content, str):
            preview = content[:200]
        else:
            preview = str(content)[:200]

        print(
            f"[{_ts()}] [MODEL] "
            f"last_message={preview!r}"
        )

    try:
        response = handler(request)

        model_message = response.result[-1] if response.result else None
        response_content = getattr(model_message, "content", "")

        if isinstance(response_content, str):
            response_preview = response_content[:200]
        else:
            response_preview = str(
                response_content
            )[:200]

        print(
            f"[{_ts()}] [MODEL] "
            f"response={response_preview!r}"
        )

        tool_calls = getattr(
            model_message,
            "tool_calls",
            None
        )

        if tool_calls:
            print(
                f"[{_ts()}] [MODEL] "
                f"tool_calls={tool_calls}"
            )

        return response

    except Exception as e:
        print(
            f"[{_ts()}] [MODEL] "
            f"ERROR={type(e).__name__}: {e}"
        )

        raise


@wrap_tool_call
def tool_logging_middleware(request, handler):
    """
    Log tool calls and tool results.
    """

    tool_call = getattr(
        request,
        "tool_call",
        None
    )

    if tool_call:
        print(
            f"[{_ts()}] [TOOL] "
            f"call={tool_call}"
        )

    try:
        response = handler(request)

        print(
            f"[{_ts()}] [TOOL] "
            f"success={response}"
        )

        return response

    except Exception as e:
        print(
            f"[{_ts()}] [TOOL] "
            f"ERROR={type(e).__name__}: {e}"
        )

        raise


def get_logging_middleware():
    return [
        model_logging_middleware,
        tool_logging_middleware,
    ]

