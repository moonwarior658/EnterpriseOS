import re


REPEATED_WHITESPACE = re.compile(r"\s+")
TRAILING_PUNCTUATION = ".,;:!?"


def clean_product_text(value: str) -> str:
    collapsed = REPEATED_WHITESPACE.sub(" ", value.strip())
    return collapsed.rstrip(TRAILING_PUNCTUATION).rstrip()


def normalize_product_text(value: str) -> str:
    return clean_product_text(value).casefold().replace("ё", "е")
