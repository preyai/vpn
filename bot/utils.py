import re

_MD_SPECIAL = re.compile(r'([_*\[\]()~`>#+=|{}.!\-\\])')


def md(text: str) -> str:
    """Escape a string for Telegram MarkdownV2."""
    return _MD_SPECIAL.sub(r'\\\1', str(text))
