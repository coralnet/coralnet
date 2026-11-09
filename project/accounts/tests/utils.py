def link_from_text(text: str) -> str:
    """
    Find a link/URL in the text and return it.
    We assume the first link found is the desired one, and we assume
    there is such a link.
    Not a rock solid implementation, but good enough for some tests.
    """
    for word in text.split():
        if '://' in word:
            return word
    raise ValueError("Couldn't find a link in the text.")
