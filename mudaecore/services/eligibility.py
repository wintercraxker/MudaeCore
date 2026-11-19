"""Character value thresholds."""


def effective_roll_minimum(min_kakera, ignore_reset, reset_minutes, can_claim):
    if (
        can_claim
        and ignore_reset
        and reset_minutes is not None
        and 0 <= reset_minutes <= 60
    ):
        return 0
    return min_kakera


def meets_minimum(value, minimum):
    # Missing values must not pass a zero threshold.
    return value is not None and value >= minimum


def reactive_value_target(value, enabled, snipe_threshold, roll_minimum):
    # Keep the snipe trigger and enforce the own-roll minimum.
    return (
        enabled
        and meets_minimum(value, snipe_threshold)
        and meets_minimum(value, roll_minimum)
    )
