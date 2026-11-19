import sys

sys.dont_write_bytecode = True
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def main_menu():
    from mudaecore.i18n import select_language, t

    try:
        select_language()
        from mudaecore.cli import main_menu as run_menu

        run_menu()
    except (EOFError, KeyboardInterrupt):
        print(t("exiting"))


if __name__ == "__main__":
    main_menu()
