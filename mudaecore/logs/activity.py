from mudaecore.i18n import t
from mudaecore.visual import horizontal_gradient


def activity_title():
    return "\n".join(
        horizontal_gradient(line) for line in t("activity_ascii").splitlines()
    )
