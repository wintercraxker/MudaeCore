from mudaecore.i18n import t


def start_task_once(client, name, coroutine_factory, log_function):
    if not hasattr(client, "background_tasks"):
        client.background_tasks = {}
    current = client.background_tasks.get(name)
    if current is not None and not current.done():
        return current
    task = client.loop.create_task(coroutine_factory(), name=name)
    client.background_tasks[name] = task

    def report_failure(completed):
        if completed.cancelled():
            return
        error = completed.exception()
        if error is not None:
            log_function(
                t("task_failed", name=name, error=error), client.preset_name, "ERROR"
            )

    task.add_done_callback(report_failure)
    return task
