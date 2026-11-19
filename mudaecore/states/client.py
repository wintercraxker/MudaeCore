def initialize_client(
    client,
    *,
    target_channel_id,
    min_kakera,
    delay_seconds,
    mudae_prefix,
    preset_name,
    key_mode,
    snipe_mode,
    snipe_delay,
    snipe_ignore_min_kakera_reset,
    wishlist,
    series_snipe_mode,
    series_snipe_delay,
    series_wishlist,
    roll_speed,
    kakera_snipe_mode_preset,
    kakera_snipe_threshold_preset,
    enable_reactive_self_snipe_preset,
    rolling_enabled,
    kakera_reaction_snipe_mode_preset,
    kakera_reaction_snipe_delay_preset,
    kakera_reaction_snipe_targets,
    humanization_enabled,
    humanization_window_minutes,
    humanization_inactivity_seconds,
    dk_power_management,
    skip_initial_commands,
    use_slash_rolls,
    only_chaos,
    reactive_snipe_delay,
    auto_pokeslot_enabled,
    pokeslot_interval_minutes,
    auto_steal_enabled,
    steal_delay,
    target_guild_id,
    route_available,
):
    # Config init
    client.preset_name = preset_name
    client.min_kakera = min_kakera
    client.snipe_mode = snipe_mode
    client.snipe_delay = snipe_delay
    client.snipe_ignore_min_kakera_reset = snipe_ignore_min_kakera_reset
    client.wishlist = [w.lower() for w in wishlist]
    client.series_snipe_mode = series_snipe_mode
    client.series_snipe_delay = series_snipe_delay
    client.series_wishlist = [sw.lower() for sw in series_wishlist]
    client.muda_name = preset_name
    client.claim_right_available = False
    client.target_channel_id = target_channel_id
    client.target_guild_id = target_guild_id
    client.roll_speed = roll_speed
    client.mudae_prefix = mudae_prefix
    client.key_mode = key_mode
    client.delay_seconds = delay_seconds
    client.sniped_messages = set()
    client.snipe_happened = False
    client.series_sniped_messages = set()
    client.series_snipe_happened = False
    client.kakera_value_sniped_messages = set()
    client.is_actively_rolling = False
    client.interrupt_rolling = False
    client.current_min_kakera_for_roll_claim = client.min_kakera
    client.kakera_snipe_mode_active = kakera_snipe_mode_preset
    client.kakera_snipe_threshold = kakera_snipe_threshold_preset
    client.enable_reactive_self_snipe = enable_reactive_self_snipe_preset
    client.reactive_snipe_delay = reactive_snipe_delay
    client.rolling_enabled = rolling_enabled
    client.rt_available = False

    client.kakera_reaction_snipe_mode_active = kakera_reaction_snipe_mode_preset
    client.kakera_reaction_snipe_delay_value = kakera_reaction_snipe_delay_preset
    client.kakera_reaction_snipe_targets = [
        t.lower() for t in kakera_reaction_snipe_targets
    ]
    client.kakera_reaction_sniped_messages = set()
    client.kakera_react_available = True
    client.kakera_react_cooldown_until_utc = None

    # Pokeslot features
    client.auto_pokeslot_enabled = auto_pokeslot_enabled
    client.pokeslot_interval_minutes = pokeslot_interval_minutes
    client.pokeslot_cooldown_until_utc = None
    client.pokeslot_running = False

    # Auto-steal uses the main wishlist.
    client.auto_steal_enabled = auto_steal_enabled
    client.steal_delay = steal_delay
    client.steal_sniped_messages = set()

    # Humanization config
    client.humanization_enabled = humanization_enabled
    client.humanization_window_minutes = humanization_window_minutes
    client.humanization_inactivity_seconds = humanization_inactivity_seconds

    # Power and key settings
    client.dk_power_management = dk_power_management
    client.skip_initial_commands = skip_initial_commands
    client.dk_stock_count = 0
    client.only_chaos = only_chaos

    # State tracking
    client.next_claim_reset_at_utc = None
    client.claim_cooldown_until_utc = None
    client.snipe_watch = {}
    client.snipe_watch_expiry_seconds = 180
    client.snipe_globally_disabled_until = None

    # IMPROVED RATE LIMIT TRACKING
    client.last_command_time = 0.0
    client.command_delay_base = 2.0  # Increased base delay
    client.rate_limit_buffer = 1.0  # Increased buffer
    client.consecutive_rate_limits = 0
    client.rate_limit_backoff = 1.0
    client.max_backoff = 30.0
    client.global_rate_limit_until = 0.0

    # Slash command internal state
    client.use_slash_rolls = bool(use_slash_rolls and route_available)
    client.mudae_slash_cache = {}
    client.mudae_slash_missing = set()
    client.mudae_session_id = None
    client.slash_fail_streak = 0
    client.slash_fail_threshold = 3
    client.slash_min_interval = (
        max(2.0, float(roll_speed)) if roll_speed else 2.0
    )  # Increased
    client.slash_max_backoff = 10.0  # Increased
    client.last_slash_attempt = 0.0
    client.slash_rate_limited_until = 0.0
    client.key_limit_hit = False
