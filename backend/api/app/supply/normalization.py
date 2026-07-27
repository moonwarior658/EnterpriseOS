import re


REPEATED_WHITESPACE = re.compile(r"\s+")


def normalize_product_text(value: str) -> str:
    return REPEATED_WHITESPACE.sub(
        " ",
        value.strip().casefold().replace("ё", "е"),
    )
