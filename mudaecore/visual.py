from dataclasses import dataclass
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import textwrap
import unicodedata

from inquirer import errors
import inquirer
from inquirer.render.console import ConsoleRender

ART_PATH = Path(__file__).resolve().parent.parent / "assets" / "azusa.txt"
TITLE_PATH = ART_PATH.with_name("title.txt")
RUNTIME_ART_PATH = ART_PATH.with_name("runtime_character.txt")
PALETTE = ((114, 87, 168), (167, 139, 250), (212, 165, 201), (233, 221, 245))
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def ansi_supported():
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return os.environ.get("TERM") not in (None, "dumb")
    # Windows console capabilities are independent of inherited TERM values.
    try:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.windll.kernel32
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetStdHandle.restype = wintypes.HANDLE
        kernel.GetConsoleMode.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = kernel.GetStdHandle(-11)
        mode = wintypes.DWORD()
        return bool(
            kernel.GetConsoleMode(handle, ctypes.byref(mode))
            and kernel.SetConsoleMode(handle, mode.value | 0x0004)
        )
    except (AttributeError, OSError):
        return False


def color_supported():
    if "NO_COLOR" in os.environ or not ansi_supported():
        return False
    return (
        os.name == "nt"
        or os.environ.get("COLORTERM") in ("truecolor", "24bit")
        or any(value in os.environ.get("TERM", "") for value in ("direct", "kitty"))
    )


def terminal_size():
    try:
        return os.get_terminal_size(sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
        return shutil.get_terminal_size(fallback=(80, 24))


def clear_terminal():
    if not sys.stdout.isatty():
        return
    if ansi_supported():
        sys.stdout.write("\033[0m\033[2J\033[3J\033[H")
        sys.stdout.flush()
    elif os.name == "nt":
        subprocess.run(["cmd", "/c", "cls"], check=False)
    elif os.environ.get("TERM") not in (None, "dumb") and shutil.which("clear"):
        subprocess.run(["clear"], check=False)


def visible_width(text):
    return sum(
        (
            0
            if unicodedata.combining(c)
            else 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
        )
        for c in ANSI.sub("", text)
    )


class OptionLabel(str):
    def __new__(cls, label, value):
        result = super().__new__(cls, label + "  " + value)
        result.label, result.value = label, value
        return result


def wrap_visible(text, width):
    lines = []
    for paragraph in ANSI.sub("", str(text)).split("\n"):
        if not paragraph:
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                paragraph,
                width=max(1, width),
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [""]
        )
    return lines


def read_runtime_character():
    try:
        return RUNTIME_ART_PATH.read_text(encoding="utf-8-sig"), None
    except (OSError, UnicodeError) as exc:
        return "", exc


def configuration_frame(render, size):
    """Fit a configuration page in physical terminal cells, including controls."""
    from mudaecore.i18n import t

    render.configuration_blocked = False
    width, height = max(1, size.columns - 2), max(1, size.lines - 2)
    if width < 30 or height < 12:
        render.configuration_blocked = True
        return wrap_visible(t("cfg_resize"), width)[:height]
    title = brand_title().splitlines()
    if max(map(visible_width, title)) > width:
        title = ["MUDAE CORE"]
    header = wrap_visible(render.get_header(), width)
    prefix = title + [""] + header + [""]
    is_text = isinstance(render.question, inquirer.Text)
    help_map = getattr(render.question, "context_help", {})
    selected = None
    if not is_text:
        choice = render.question.choices[render.current]
        selected = getattr(choice, "value", choice)
    help_lines = (
        wrap_visible(help_map.get(selected, ""), width)
        if help_map.get(selected)
        else []
    )
    footer = (
        ["", "-" * min(48, width)]
        + help_lines
        + [""]
        + wrap_visible(t("cfg_text_keys") if is_text else t("cfg_menu_keys"), width)
    )
    budget = height - len(prefix) - len(footer)
    if budget < 3:
        prefix = [paint("MUDAE CORE")] + header + [""]
        budget = height - len(prefix) - len(footer)
    if budget < 1:
        render.configuration_blocked = True
        return wrap_visible(t("cfg_resize"), width)[:height]
    rows = []
    if is_text:
        position = len(render.current) - render.cursor_offset
        displayed = (
            "*" * len(render.current)
            if isinstance(render.question, inquirer.Password)
            else render.current
        )
        left = displayed[:position]
        while left and visible_width(left) > width - 4:
            left = left[1:]
        value = left + "\u2588" + displayed[position:]
        rows = ["> " + wrap_visible(value, width - 2)[0]]
    else:
        mapping = getattr(render.question, "option_rows", {})
        label_width = max(
            (visible_width(pair[0]) for pair in mapping.values()), default=0
        )
        value_width = max(
            (visible_width(pair[1]) for pair in mapping.values()), default=0
        )
        blocks = []
        for index, choice in enumerate(render.question.choices):
            value = getattr(choice, "value", choice)
            label = str(choice)
            if value in mapping:
                label, detail = mapping[value]
                if label_width + value_width + 4 <= width:
                    lines = [
                        label + " " * (label_width - visible_width(label) + 2) + detail
                    ]
                else:
                    lines = wrap_visible(label, width - 2) + wrap_visible(
                        detail, width - 4
                    )
            else:
                lines = wrap_visible(label, width - 2)
            blocks.append(
                [("> " if index == render.current else "  ") + lines[0]]
                + ["  " + line for line in lines[1:]]
            )
        if len(blocks[render.current]) > budget:
            render.configuration_blocked = True
            return wrap_visible(t("cfg_resize"), width)[:height]
        page = []
        used = 0
        start = 0
        # Stable pages: navigation within a page never shifts option rows.
        for index, block in enumerate(blocks):
            if used + len(block) > budget and page:
                if start <= render.current < index:
                    break
                page, used, start = [], 0, index
            page.extend(block[:budget])
            used += len(block[:budget])
        rows = page
        if start or sum(map(len, blocks)) > budget:
            footer[0] = t("cfg_visible_options", first=start + 1, total=len(blocks))
    lines = prefix + rows[:budget] + footer
    return [
        paint(line, PALETTE[1] if line.startswith("> ") else PALETTE[-1])
        for line in lines[:height]
    ]


def paint(text, color=PALETTE[-1], enabled=None):
    if enabled is None:
        enabled = color_supported()
    return (
        f"\033[38;2;{color[0]};{color[1]};{color[2]}m{text}\033[0m"
        if enabled and text
        else text
    )


def gradient(text, colors=PALETTE, enabled=None):
    lines = text.splitlines(keepends=True)
    if enabled is None:
        enabled = color_supported()
    if not enabled:
        return text
    result = []
    for index, line in enumerate(lines):
        position = index * (len(colors) - 1) / max(1, len(lines) - 1)
        start = min(int(position), len(colors) - 1)
        end = min(start + 1, len(colors) - 1)
        fraction = position - start
        rgb = tuple(
            round(a + (b - a) * fraction) for a, b in zip(colors[start], colors[end])
        )
        content = line.rstrip("\r\n")
        result.append(paint(content, rgb, True) + line[len(content) :])
    return "".join(result)


def horizontal_gradient(text, colors=PALETTE, enabled=None):
    if enabled is None:
        enabled = color_supported()
    if not enabled:
        return text
    output = []
    for index, character in enumerate(text):
        position = index * (len(colors) - 1) / max(1, len(text) - 1)
        start = min(int(position), len(colors) - 1)
        end = min(start + 1, len(colors) - 1)
        fraction = position - start
        rgb = tuple(
            round(a + (b - a) * fraction) for a, b in zip(colors[start], colors[end])
        )
        output.append(paint(character, rgb, True))
    return "".join(output)


def brand_title():
    return "\n".join(
        horizontal_gradient(line)
        for line in TITLE_PATH.read_text(encoding="utf-8").splitlines()
    )


def execution_layout(rows, activity, instructions):
    size = terminal_size()
    label_width = max((visible_width(label) for label, _ in rows), default=0)
    content = brand_title().splitlines() + [""]
    rule = paint("-" * min(48, max(1, size.columns - 1)), (153, 151, 164))
    content.append(rule)
    for label, value in rows:
        content.append(
            paint(label.ljust(label_width), (176, 171, 190)) + "  " + paint(str(value))
        )
    # Keep most of the viewport available for activity.
    raw, error = read_runtime_character()
    if error:
        from mudaecore.i18n import t

        content.append(paint(t("runtime_character_error"), (212, 145, 160)))
    else:
        art = gradient(raw).splitlines()
        art_width = max((visible_width(line) for line in art), default=0)
        content_width = max(map(visible_width, content))
        if (
            art
            and len(art) <= size.lines // 3
            and size.columns >= max(100, content_width + 4 + art_width + 1)
        ):
            if len(art) > len(content):
                content += [""] * (len(art) - len(content))
            for index, line in enumerate(art):
                content[index] += (
                    " " * (content_width + 4 - visible_width(content[index])) + line
                )
    content += (
        [rule]
        + activity.splitlines()
        + [rule, paint(instructions, (176, 171, 190)), ""]
    )
    return "\n".join(content)


@dataclass
class Panel:
    lines: list
    row: int
    column: int
    menu_width: int
    size: os.terminal_size


def compose_panel(menu, show_art=True, align_top=False):
    size = terminal_size()
    raw_art = ART_PATH.read_text(encoding="utf-8") if show_art else ""
    art = gradient(raw_art).splitlines()
    art_width = max((visible_width(line) for line in art), default=0)
    menu_width = max((visible_width(line) for line in menu), default=0)
    column = art_width + 4
    wide = bool(art) and size.columns >= column + menu_width + 2
    row = (0 if align_top else len(art) // 3) if wide else len(art) + bool(art)
    if not wide:
        return Panel(art + ([""] if art else []) + menu, row, 0, menu_width, size)
    lines = []
    for index in range(max(len(art), row + len(menu))):
        left = art[index] if index < len(art) else ""
        right = menu[index - row] if row <= index < row + len(menu) else ""
        lines.append(left + " " * (column - visible_width(left)) + right)
    return Panel(lines, row, column, menu_width, size)


def show_banner(menu, show_art=True):
    panel = compose_panel(menu, show_art)
    print("\n".join(panel.lines))
    sys.stdout.flush()
    return panel


def update_menu(panel, menu, previous=None):
    # Only touch the menu columns; the drawing is never repainted on arrows.
    sys.stdout.write("\033[s")
    for index, line in enumerate(menu):
        if previous is not None and line == previous[index]:
            continue
        sys.stdout.write(f"\033[u\033[{len(panel.lines) - panel.row - index}A\r")
        if panel.column:
            sys.stdout.write(f"\033[{panel.column}C")
        sys.stdout.write(line + " " * max(0, panel.menu_width - visible_width(line)))
    sys.stdout.write("\033[u")
    sys.stdout.flush()


def choose_language(menu_text, prompt, invalid):
    if sys.stdin.isatty() and ansi_supported():
        from mudaecore.i18n import t

        question = inquirer.List(
            "language",
            message=menu_text.splitlines()[0],
            choices=[
                ("Português (Brasil)", "1"),
                ("English", "2"),
                ("Español", "3"),
            ],
        )
        answer = inquirer.prompt(
            [question],
            render=MenuRenderer(hint=t("language_navigation")),
            raise_keyboard_interrupt=True,
        )
        return answer["language"]
    menu = []
    menu.extend(brand_title().splitlines() + [""])
    lines = menu_text.splitlines()
    art_width = max(map(len, ART_PATH.read_text(encoding="utf-8").splitlines()))
    if ansi_supported() and terminal_size().columns < art_width + 4 + len(lines[0]) + 2:
        lines[:1] = lines[0].split(" / ")
    for line in lines:
        marker = (
            "> "
            if line.startswith("[1]")
            else "  "
            if line.startswith("[2]") or line.startswith("[3]")
            else ""
        )
        menu.append(paint(marker + line, PALETTE[1] if marker else PALETTE[-1]))
    menu += ["", ""]
    panel = show_banner(menu)
    prompt_row = panel.row + len(menu) - 1
    positioned = ansi_supported() and len(panel.lines) < panel.size.lines
    first_prompt = paint(prompt)
    if positioned:
        first_prompt = (
            f"\033[{len(panel.lines) - prompt_row}A\r"
            + (f"\033[{panel.column}C" if panel.column else "")
            + first_prompt
        )
    while True:
        try:
            selection = input(first_prompt).strip()
        finally:
            if positioned:
                distance = len(panel.lines) - prompt_row - 1
                if distance:
                    sys.stdout.write(f"\033[{distance}B")
                sys.stdout.write("\r")
                positioned = False
        if selection in ("1", "2"):
            return selection
        print(paint(invalid, (212, 145, 160)))
        first_prompt = paint(prompt)


class MenuRenderer(ConsoleRender):
    def __init__(self, *, show_art=True, preserve_logs=False, hint="", **kwargs):
        super().__init__(**kwargs)
        self.show_art = show_art
        self.preserve_logs = preserve_logs
        self.hint = hint

    def clear_eos(self):
        # Inquirer calls this before rendering; it must not erase the banner or logs.
        pass

    def _event_loop(self, render):
        panel = None
        previous = None
        configuration = getattr(render.question, "configuration", False)
        is_text = isinstance(render.question, inquirer.Text)
        original_input = render.process_input

        def process_input(pressed):
            if configuration and pressed == "\x1b":
                raise errors.EndOfInput(None)
            if (
                configuration
                and getattr(render, "configuration_blocked", False)
                and pressed != "\x03"
            ):
                return
            return original_input(pressed)

        render.process_input = process_input
        try:
            while True:
                current_size = terminal_size()
                if configuration:
                    art_lines = (
                        ART_PATH.read_text(encoding="utf-8").splitlines()
                        if self.show_art
                        else []
                    )
                    art_width = max(map(visible_width, art_lines), default=0)
                    # Reserve the artwork BEFORE wrapping descriptions and columns.
                    side_art = (
                        bool(art_lines)
                        and current_size.columns - art_width - 4 >= 60
                        and len(art_lines) < current_size.lines - 1
                    )
                    content_size = (
                        os.terminal_size(
                            (current_size.columns - art_width - 4, current_size.lines)
                        )
                        if side_art
                        else current_size
                    )
                    menu = configuration_frame(render, content_size)
                    menu_width = max(map(visible_width, menu), default=0)
                    if (
                        panel is not None
                        and bool(panel.column) == side_art
                        and current_size == panel.size
                        and len(menu) == len(previous)
                        and panel.column + menu_width < current_size.columns
                    ):
                        panel.menu_width = max(panel.menu_width, menu_width)
                        update_menu(panel, menu, previous)
                    else:
                        clear_terminal()
                        candidate = compose_panel(menu, side_art, align_top=True)
                        if len(candidate.lines) > current_size.lines - 1 or any(
                            visible_width(line) >= current_size.columns
                            for line in candidate.lines
                        ):
                            candidate = compose_panel(menu, False)
                        panel = candidate
                        print("\n".join(panel.lines), flush=True)
                    previous = menu
                    self._process_input(render)
                    continue
                header = render.get_header()
                art_width = max(
                    map(len, ART_PATH.read_text(encoding="utf-8").splitlines())
                )
                titles = (
                    header.splitlines()
                    if configuration
                    else (
                        header.split(" / ")
                        if current_size.columns < art_width + 6 + len(header)
                        else [header]
                    )
                )
                menu = (
                    brand_title().splitlines()
                    + [""]
                    + [paint(title) for title in titles]
                    + [""]
                )
                for message, symbol, _ in render.get_options():
                    active = symbol.lstrip().startswith(">")
                    menu.append(
                        paint(
                            f"{symbol} {message}", PALETTE[1] if active else PALETTE[-1]
                        )
                    )
                if is_text:
                    position = len(render.current) - render.cursor_offset
                    width = max(10, current_size.columns - 8)
                    start = max(0, position - width + 1)
                    displayed = (
                        "*" * len(render.current)
                        if isinstance(render.question, inquirer.Password)
                        else render.current
                    )
                    value = displayed[start:position] + "\u2588" + displayed[position:]
                    menu += [paint("> " + value[:width], PALETTE[1])]
                if configuration:
                    from mudaecore.i18n import t

                    help_map = getattr(render.question, "context_help", {})
                    if not is_text and help_map:
                        selected = render.question.choices[render.current]
                        selected = getattr(selected, "value", selected)
                        description = help_map.get(selected, "")
                        menu += [paint("-" * min(48, current_size.columns - 1))]
                        menu += [
                            paint(line)
                            for line in textwrap.wrap(
                                description, max(20, current_size.columns - 8)
                            )
                        ]
                    menu += [
                        "",
                        paint(t("cfg_text_keys") if is_text else t("cfg_menu_keys")),
                    ]
                if self.hint:
                    hints = (
                        self.hint.split(" | ")
                        if current_size.columns < art_width + 6 + len(self.hint)
                        else [self.hint]
                    )
                    menu += [""] + [paint(hint, (176, 171, 190)) for hint in hints]
                if self._previous_error:
                    menu.append(paint(str(self._previous_error), (212, 145, 160)))
                can_update = (
                    panel is not None
                    and ansi_supported()
                    and not self.preserve_logs
                    and current_size == panel.size
                    and len(menu) < current_size.lines
                    and len(menu) == len(previous)
                    and max(map(visible_width, menu)) <= panel.menu_width
                )
                if panel is None or menu != previous or current_size != panel.size:
                    if can_update:
                        update_menu(panel, menu, previous)
                    else:
                        if configuration and panel is not None:
                            clear_terminal()
                        panel = show_banner(
                            menu, self.show_art and (panel is None or configuration)
                        )
                    previous = menu
                self._process_input(render)
        except errors.EndOfInput as result:
            return result.selection
