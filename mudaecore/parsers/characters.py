import re
from mudaecore.constants import CLAIM_EMOJIS

_KAKERA_VALUE = re.compile(
    r"(?<![\w.,])(?P<value>\d{1,3}(?:,\d{3})+|\d+)\*{0,2}\s*<:kakera:\d+>"
)


def parse_kakera_value(description):
    match = _KAKERA_VALUE.search(description or "")
    return int(match.group("value").replace(",", "")) if match else None


def is_character_embed(embed):
    # Reliable check: Characters have an image but NO thumbnail
    if not embed:
        return False

    has_image = embed.image and embed.image.url
    has_thumbnail = embed.thumbnail and embed.thumbnail.url

    return has_image and not has_thumbnail


def has_claim_option(message, embed):
    if not message.components:
        return True
    for comp in message.components:
        for btn in comp.children:
            if (
                hasattr(btn, "emoji")
                and btn.emoji
                and hasattr(btn.emoji, "name")
                and btn.emoji.name in CLAIM_EMOJIS
            ):
                return True
    return False


def count_chaos_keys(embed):
    # Extracts key count from description. Format: <:key:ID> (**N**)
    if not embed or not embed.description:
        return 0

    desc = embed.description
    key_pattern = r"<:(?:chaos)?key:\d+>\s*\(\*\*(\d+)\*\*\)"
    matches = re.findall(key_pattern, desc, re.IGNORECASE)

    chaos_count = 0
    for match in matches:
        try:
            if int(match) >= 10:
                chaos_count += 1
        except ValueError:
            continue

    return chaos_count


def get_character_owner(embed):
    if not embed or not embed.footer or not embed.footer.text:
        return None

    footer_text = embed.footer.text
    belongs_pattern = r"[Bb]elongs to\s+(.+?)$"
    match = re.search(belongs_pattern, footer_text)

    if match:
        return match.group(1).strip().rstrip().lower()

    return None
