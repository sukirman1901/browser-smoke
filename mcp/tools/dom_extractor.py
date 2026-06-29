def classify_inputs(elements: list[dict]) -> dict:
    """Classify DOM elements into categories for smoke testing."""
    buttons = [e for e in elements if e["tag"] == "button" and e["visible"] and e["enabled"]]
    inputs = [e for e in elements if e["tag"] == "input" and e["visible"]]
    links = [e for e in elements if e["tag"] == "a" and e["visible"]]
    others = [e for e in elements if e not in buttons + inputs + links]
    return {
        "buttons": buttons,
        "inputs": inputs,
        "links": links,
        "others": others,
        "total": len(elements),
    }


def guess_input_value(input_el: dict) -> str:
    """Guess a test value based on input type."""
    t = input_el.get("type", "text")
    if "email" in t:
        return "test@test.com"
    if "password" in t or "pass" in t:
        return "Test1234!"
    if "search" in t:
        return "test search"
    if "url" in t:
        return "https://example.com"
    if "tel" in t or "phone" in t:
        return "08123456789"
    if "number" in t:
        return "123"
    return "test"
