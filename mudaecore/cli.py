import inquirer
from mudaecore.config import load_presets
from mudaecore.config_editor import configuration_menu
from mudaecore.services.lifecycle import start_preset_thread
from mudaecore.i18n import t
from mudaecore.visual import MenuRenderer, paint, clear_terminal, execution_layout
from mudaecore.logs.console import (
    menu_session,
    configure_external_logging,
    configure_log_context,
    report_summary,
)
from mudaecore.states.presentation import summary
from mudaecore.logs.activity import activity_title


def prompt(questions, *, show_art=True, preserve_logs=False):
    try:
        return inquirer.prompt(
            questions,
            render=MenuRenderer(show_art=show_art, preserve_logs=preserve_logs),
            raise_keyboard_interrupt=True,
        )
    except KeyboardInterrupt:
        print(t("prompt_cancelled"))
        return None


def execution_header(count, counts=None):
    if counts is None:
        counts = dict(
            selected=count,
            started=0,
            ready=0,
            pending=count,
            unknown=0,
            errors=0,
            stopped=0,
        )
    count = counts["selected"]
    names = [entry["name"] for entry in summary.entries]
    rows = [
        (t("stats_initial"), t("summary_requested")),
        (
            t("stats_preset") if count == 1 else t("summary_selected"),
            names[-1] if count == 1 and names else count,
        ),
    ]
    print(execution_layout(rows, activity_title(), t("execution_return")))


def execution_view(threads):
    try:
        input()
    except EOFError:
        for thread in threads:
            if thread is not None:
                thread.join()


def main_menu():
    presets = load_presets()
    configure_log_context(presets)
    summary.reset()
    configure_external_logging()
    threads = []
    first_menu = True
    while True:
        running = any(thread is not None and thread.is_alive() for thread in threads)
        selected = []
        with menu_session():
            if not first_menu:
                clear_terminal()
            first_menu = False
            opts = [
                (t("menu_single"), "single"),
                (t("menu_multiple"), "multiple"),
                (t("cfg_title"), "configuration"),
                (t("menu_exit"), "exit"),
            ]
            answer = prompt(
                [inquirer.List("opt", message=t("menu_prompt"), choices=opts)]
            )
            if not answer or answer["opt"] == "exit":
                print(paint(t("exiting")))
                return
            if answer["opt"] == "configuration":
                presets = configuration_menu(presets, prompt)
                continue
            if answer["opt"] == "single":
                if not running:
                    clear_terminal()
                choice = prompt(
                    [
                        inquirer.List(
                            "p",
                            message=t("preset_prompt"),
                            choices=list(presets.keys()),
                        )
                    ]
                )
                if choice:
                    selected = [choice["p"]]
            elif answer["opt"] == "multiple":
                if not running:
                    clear_terminal()
                choice = prompt(
                    [
                        inquirer.Checkbox(
                            "p",
                            message=t("presets_prompt"),
                            choices=list(presets.keys()),
                        )
                    ]
                )
                if choice:
                    selected = choice["p"]
            if selected:
                indices = summary.select(selected)
                if not running:
                    clear_terminal()
                execution_header(len(selected), summary.snapshot())
        if selected:
            for index, name in zip(indices, selected):
                worker = start_preset_thread(name, presets[name])
                threads.append(worker)
                summary.attach(index, worker)
            report_summary()
            execution_view(threads)
