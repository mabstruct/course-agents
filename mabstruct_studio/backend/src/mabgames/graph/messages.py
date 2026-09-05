"""Reading agent output.

`message_text` exists because Anthropic models return content as a list of blocks
(thinking + text). Never assume `message.content` is a string.
"""


def message_text(message) -> str:
    """Plain text from an AIMessage; Opus may return thinking blocks as a list."""
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(part for part in parts if part)
    return str(content)


def tool_names_from_messages(messages) -> list[str]:
    """Which tools the agent actually called — used when a build has to explain itself."""
    names: list[str] = []
    for msg in messages:
        for call in getattr(msg, "tool_calls", None) or []:
            names.append(call.get("name", "?"))
    return names
