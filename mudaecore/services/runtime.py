from mudaecore.i18n import t, with_statistics
import asyncio
import discord
from discord.ext import commands
import re
import datetime
from datetime import timezone
import logging
import time
import random
from discord.utils import time_snowflake

try:
    from discord.http import Route
except ImportError:
    Route = None


from mudaecore.constants import (
    BOT_NAME,
    TARGET_BOT_ID,
    CLAIM_EMOJIS,
    KAKERA_EMOJIS,
    CHAOS_KAKERA_EMOJIS,
)
from mudaecore.parsers.characters import (
    is_character_embed,
    has_claim_option,
    count_chaos_keys,
    get_character_owner,
    parse_kakera_value,
)
from mudaecore.states.client import initialize_client
from mudaecore.services.eligibility import (
    effective_roll_minimum,
    meets_minimum,
    reactive_value_target,
)
from mudaecore.services.tasks import start_task_once


def run_bot(
    token,
    prefix,
    target_channel_id,
    roll_command,
    min_kakera,
    delay_seconds,
    mudae_prefix,
    log_function,
    preset_name,
    key_mode,
    start_delay,
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
):

    client = commands.Bot(
        command_prefix=prefix, chunk_guilds_at_startup=False, self_bot=True
    )

    # Clean up console logging
    discord_logger = logging.getLogger("discord")
    discord_logger.propagate = False
    handlers = [
        h for h in discord_logger.handlers if isinstance(h, logging.StreamHandler)
    ]
    for h in handlers:
        discord_logger.removeHandler(h)

    initialize_client(
        client,
        target_channel_id=target_channel_id,
        min_kakera=min_kakera,
        delay_seconds=delay_seconds,
        mudae_prefix=mudae_prefix,
        preset_name=preset_name,
        key_mode=key_mode,
        snipe_mode=snipe_mode,
        snipe_delay=snipe_delay,
        snipe_ignore_min_kakera_reset=snipe_ignore_min_kakera_reset,
        wishlist=wishlist,
        series_snipe_mode=series_snipe_mode,
        series_snipe_delay=series_snipe_delay,
        series_wishlist=series_wishlist,
        roll_speed=roll_speed,
        kakera_snipe_mode_preset=kakera_snipe_mode_preset,
        kakera_snipe_threshold_preset=kakera_snipe_threshold_preset,
        enable_reactive_self_snipe_preset=enable_reactive_self_snipe_preset,
        rolling_enabled=rolling_enabled,
        kakera_reaction_snipe_mode_preset=kakera_reaction_snipe_mode_preset,
        kakera_reaction_snipe_delay_preset=kakera_reaction_snipe_delay_preset,
        kakera_reaction_snipe_targets=kakera_reaction_snipe_targets,
        humanization_enabled=humanization_enabled,
        humanization_window_minutes=humanization_window_minutes,
        humanization_inactivity_seconds=humanization_inactivity_seconds,
        dk_power_management=dk_power_management,
        skip_initial_commands=skip_initial_commands,
        use_slash_rolls=use_slash_rolls,
        only_chaos=only_chaos,
        reactive_snipe_delay=reactive_snipe_delay,
        auto_pokeslot_enabled=auto_pokeslot_enabled,
        pokeslot_interval_minutes=pokeslot_interval_minutes,
        auto_steal_enabled=auto_steal_enabled,
        steal_delay=steal_delay,
        target_guild_id=target_guild_id,
        route_available=Route is not None,
    )

    async def safe_command_delay():
        """Delay commands with exponential backoff."""
        now = time.time()

        # Check global rate limit
        if now < client.global_rate_limit_until:
            wait = client.global_rate_limit_until - now
            log_function(t("global_rate_limit", wait=wait), preset_name, "WARN")
            await asyncio.sleep(wait)
            now = time.time()

        elapsed = now - client.last_command_time
        required_delay = (
            client.command_delay_base * client.rate_limit_backoff
            + random.uniform(0, 0.5)
        )

        if elapsed < required_delay:
            await asyncio.sleep(required_delay - elapsed)

        client.last_command_time = time.time()

    async def handle_rate_limit_response(retry_after=None):
        """Handle rate limits with backoff."""
        client.consecutive_rate_limits += 1

        if retry_after:
            wait_time = min(retry_after + client.rate_limit_buffer, client.max_backoff)
        else:
            wait_time = min(
                client.command_delay_base * (2**client.consecutive_rate_limits),
                client.max_backoff,
            )

        # Update backoff multiplier
        client.rate_limit_backoff = min(client.rate_limit_backoff * 1.5, 5.0)

        # Set global rate limit
        client.global_rate_limit_until = time.time() + wait_time

        log_function(
            t(
                "rate_limited",
                consecutive_rate_limits=client.consecutive_rate_limits,
                wait_time=wait_time,
            ),
            preset_name,
            "ERROR",
        )
        await asyncio.sleep(wait_time)
        client.last_command_time = time.time()

        # Reset backoff after successful wait
        if client.consecutive_rate_limits >= 3:
            client.command_delay_base = min(client.command_delay_base * 1.2, 5.0)
            log_function(
                t("delay_increased", command_delay_base=client.command_delay_base),
                preset_name,
                "WARN",
            )

    async def reset_rate_limit_backoff():
        """Reduce backoff after successful requests."""
        while not client.is_closed():
            await asyncio.sleep(300)  # Every 5 minutes
            if client.consecutive_rate_limits == 0 and client.rate_limit_backoff > 1.0:
                client.rate_limit_backoff = max(1.0, client.rate_limit_backoff * 0.8)
                client.command_delay_base = max(2.0, client.command_delay_base * 0.9)
                log_function(
                    t("delay_reduced", rate_limit_backoff=client.rate_limit_backoff),
                    preset_name,
                    "INFO",
                )
            client.consecutive_rate_limits = max(0, client.consecutive_rate_limits - 1)

    async def health_monitor_task():
        # Reconnect if gateway drops
        unhealthy_streak = 0
        max_streak = 3
        while not client.is_closed():
            await asyncio.sleep(60)
            if client.latency == float("inf"):
                unhealthy_streak += 1
                log_function(
                    t(
                        "connection_lost",
                        unhealthy_streak=unhealthy_streak,
                        max_streak=max_streak,
                    ),
                    preset_name,
                    "ERROR",
                )
            else:
                if unhealthy_streak > 0:
                    log_function(
                        t("reconnected", latency_ms=client.latency * 1000),
                        preset_name,
                        "INFO",
                    )
                unhealthy_streak = 0
            if unhealthy_streak >= max_streak:
                log_function(t("connection_restart"), preset_name, "ERROR")
                try:
                    await client.close()
                except Exception:
                    pass
                return

    async def auto_pokeslot_task():
        """Run Pokeslot with cooldown tracking."""
        if not client.auto_pokeslot_enabled:
            return

        await asyncio.sleep(start_delay + 10)

        while not client.is_closed():
            try:
                now_utc = datetime.datetime.now(datetime.timezone.utc)

                if (
                    client.pokeslot_cooldown_until_utc
                    and now_utc < client.pokeslot_cooldown_until_utc
                ):
                    wait_seconds = (
                        client.pokeslot_cooldown_until_utc - now_utc
                    ).total_seconds()
                    await asyncio.sleep(min(wait_seconds, 60))
                    continue

                channel = client.get_channel(client.target_channel_id)
                if not channel or (
                    client.target_guild_id
                    and channel.guild.id != client.target_guild_id
                ):
                    await asyncio.sleep(60)
                    continue

                if not client.pokeslot_running:
                    client.pokeslot_running = True
                    log_function(t("pokeslot_running"), preset_name, "POKESLOT")

                    await safe_command_delay()
                    try:
                        await channel.send(f"{client.mudae_prefix}pokeslot")
                        client.consecutive_rate_limits = 0  # Reset on success
                    except discord.HTTPException as e:
                        if e.status == 429:
                            await handle_rate_limit_response(
                                getattr(e, "retry_after", None)
                            )

                    await asyncio.sleep(5)
                    client.pokeslot_running = False

                wait_time = client.pokeslot_interval_minutes * 60 + random.uniform(
                    0, 60
                )
                await asyncio.sleep(wait_time)

            except Exception as e:
                log_function(t("pokeslot_error", error=e), preset_name, "ERROR")
                client.pokeslot_running = False
                await asyncio.sleep(60)

    def is_character_snipe_allowed() -> bool:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if (
                client.snipe_globally_disabled_until
                and now_utc < client.snipe_globally_disabled_until
            ):
                return False
            if (
                client.claim_cooldown_until_utc
                and now_utc < client.claim_cooldown_until_utc
            ):
                return False
            return True
        except Exception:
            return True

    def is_kakera_reaction_allowed() -> bool:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if client.kakera_react_available:
                return True
            if (
                client.kakera_react_cooldown_until_utc
                and now_utc >= client.kakera_react_cooldown_until_utc
            ):
                client.kakera_react_available = True
                client.kakera_react_cooldown_until_utc = None
                return True
            return False
        except Exception:
            return True

    async def snipe_watch_cleanup_task():
        while not client.is_closed():
            try:
                now_ts = time.time()
                stale = [
                    mid
                    for mid, info in client.snipe_watch.items()
                    if now_ts - info.get("ts", now_ts)
                    > client.snipe_watch_expiry_seconds
                ]
                for mid in stale:
                    client.snipe_watch.pop(mid, None)
                await asyncio.sleep(30)
            except Exception:
                await asyncio.sleep(30)

    def _refresh_session_id():
        try:
            ws = getattr(client, "ws", None)
            sid = getattr(ws, "session_id", None)
            if sid:
                client.mudae_session_id = sid
        except Exception:
            pass

    async def _fetch_mudae_slash_commands(guild_id):
        if guild_id in client.mudae_slash_cache:
            return client.mudae_slash_cache[guild_id]
        http = getattr(client, "http", None)
        if not http or Route is None:
            return None

        commands_map = {}
        data = []
        try:
            await safe_command_delay()
            route = Route(
                "GET",
                "/applications/{application_id}/commands",
                application_id=TARGET_BOT_ID,
            )
            data = await http.request(route)
            client.consecutive_rate_limits = 0  # Reset on success
        except discord.HTTPException as e:
            if e.status == 429:
                await handle_rate_limit_response(getattr(e, "retry_after", None))
            data = []
        except Exception:
            data = []

        for cmd in data:
            name = str(cmd.get("name", "")).lower()
            if name:
                commands_map[name] = cmd

        client.mudae_slash_cache[guild_id] = commands_map
        return commands_map

    async def _trigger_mudae_slash(channel, command_text):
        if not client.use_slash_rolls:
            return False
        if not channel or not getattr(channel, "guild", None):
            return False

        stripped = command_text.strip()
        if not stripped:
            return False
        now_ts = time.time()
        if client.slash_rate_limited_until and now_ts < client.slash_rate_limited_until:
            return False
        if client.last_slash_attempt:
            elapsed = now_ts - client.last_slash_attempt
            if elapsed < client.slash_min_interval:
                await asyncio.sleep(client.slash_min_interval - elapsed)
        client.last_slash_attempt = time.time()

        if " " in stripped:
            key = f"mixed:{stripped.split(' ', 1)[0].lower()}"
            if key not in client.mudae_slash_missing:
                client.mudae_slash_missing.add(key)
            return False

        base_name = stripped.lstrip("/").lower()
        guild = channel.guild
        command_map = await _fetch_mudae_slash_commands(guild.id)
        if not command_map:
            return False

        command_data = command_map.get(base_name)
        if not command_data:
            key = f"missing:{base_name}"
            if key not in client.mudae_slash_missing:
                client.mudae_slash_missing.add(key)
            return False

        _refresh_session_id()
        session_id = None
        ws = getattr(client, "ws", None)
        if ws and getattr(ws, "session_id", None):
            session_id = ws.session_id
        elif client.mudae_session_id:
            session_id = client.mudae_session_id

        if not session_id:
            return False

        payload = {
            "type": 2,
            "application_id": str(TARGET_BOT_ID),
            "guild_id": str(guild.id),
            "channel_id": str(channel.id),
            "session_id": session_id,
            "data": {
                "version": str(command_data.get("version", "")),
                "id": str(command_data.get("id", "")),
                "name": command_data.get("name"),
                "type": command_data.get("type", 1),
            },
            "nonce": str(time_snowflake(datetime.datetime.now(datetime.timezone.utc))),
        }

        invalidate_cache = False
        try:
            await safe_command_delay()
            await client.http.request(Route("POST", "/interactions"), json=payload)
            client.slash_fail_streak = 0
            client.slash_rate_limited_until = 0.0
            client.consecutive_rate_limits = 0  # Reset on success
            return True
        except discord.HTTPException as e:
            if e.status == 429:
                await handle_rate_limit_response(getattr(e, "retry_after", None))
                client.slash_rate_limited_until = time.time() + 10
            else:
                invalidate_cache = True
            client.slash_fail_streak += 1
        except Exception:
            client.slash_fail_streak += 1
            invalidate_cache = True

        if invalidate_cache:
            client.mudae_slash_cache.pop(guild.id, None)
        if client.slash_fail_streak >= client.slash_fail_threshold:
            client.use_slash_rolls = False
            log_function(t("slash_fallback"), preset_name, "WARN")
        return False

    async def send_roll_command(channel, command_name):
        cmd = (command_name or "").strip()
        if not cmd:
            return

        normalized = cmd.lstrip("/")

        if client.use_slash_rolls:
            slash_target = normalized
            slash_override_map = {"w": "wx", "h": "hx", "m": "mx"}
            slash_target = slash_override_map.get(slash_target.lower(), slash_target)
            slash_name = (
                slash_target if slash_target.startswith("/") else f"/{slash_target}"
            )
            sent = await _trigger_mudae_slash(channel, slash_name)
            if sent:
                return
            if not client.use_slash_rolls:
                await safe_command_delay()
                try:
                    await channel.send(f"{client.mudae_prefix}{normalized}")
                    client.consecutive_rate_limits = 0
                except discord.HTTPException as e:
                    if e.status == 429:
                        await handle_rate_limit_response(
                            getattr(e, "retry_after", None)
                        )
                return

        await safe_command_delay()
        try:
            await channel.send(f"{client.mudae_prefix}{normalized}")
            client.consecutive_rate_limits = 0
        except discord.HTTPException as e:
            if e.status == 429:
                await handle_rate_limit_response(getattr(e, "retry_after", None))

    @client.event
    async def on_ready():
        log_function(t("account_ready", user=client.user), preset_name, "INFO")
        start_task_once(
            client, "health_monitor_task", health_monitor_task, log_function
        )
        start_task_once(
            client, "snipe_watch_cleanup_task", snipe_watch_cleanup_task, log_function
        )
        start_task_once(
            client, "reset_rate_limit_backoff", reset_rate_limit_backoff, log_function
        )

        if client.auto_pokeslot_enabled:
            start_task_once(
                client, "auto_pokeslot_task", auto_pokeslot_task, log_function
            )
            log_function(
                t(
                    "pokeslot_enabled",
                    pokeslot_interval_minutes=client.pokeslot_interval_minutes,
                ),
                preset_name,
                "POKESLOT",
            )

        if client.auto_steal_enabled:
            log_function(t("auto_steal_enabled"), preset_name, "STEAL")

        _refresh_session_id()

        channel = client.get_channel(target_channel_id)
        if not channel:
            log_function(
                t("channel_not_found", target_channel_id=target_channel_id),
                preset_name,
                "ERROR",
            )
            await client.close()
            return

        if client.target_guild_id and channel.guild.id != client.target_guild_id:
            log_function(
                t(
                    "guild_mismatch",
                    target_guild_id=client.target_guild_id,
                    id=channel.guild.id,
                ),
                preset_name,
                "ERROR",
            )
            await client.close()
            return

        if client.rolling_enabled:
            can_send = channel.permissions_for(channel.guild.me).send_messages
            if not can_send:
                log_function(t("send_permission_missing"), preset_name, "ERROR")
                await client.close()
                return

        log_function(t("starting_delay", start_delay=start_delay), preset_name, "INFO")
        await asyncio.sleep(start_delay)

        if client.rolling_enabled:
            try:
                if client.skip_initial_commands:
                    await check_status(client, channel, client.mudae_prefix)
                else:
                    await safe_command_delay()
                    try:
                        await channel.send(
                            f"{client.mudae_prefix}limroul 777 777 777 777" # u can change this something like limroul 1 1 1 1
                        )
                        client.consecutive_rate_limits = 0
                    except discord.HTTPException as e:
                        if e.status == 429:
                            await handle_rate_limit_response(
                                getattr(e, "retry_after", None)
                            )

                    await asyncio.sleep(2.0)
                    if not client.dk_power_management:
                        await safe_command_delay()
                        try:
                            await channel.send(f"{client.mudae_prefix}dk")
                            client.consecutive_rate_limits = 0
                        except discord.HTTPException as e:
                            if e.status == 429:
                                await handle_rate_limit_response(
                                    getattr(e, "retry_after", None)
                                )
                        await asyncio.sleep(2.0)

                    await safe_command_delay()
                    try:
                        await channel.send(f"{client.mudae_prefix}daily")
                        client.consecutive_rate_limits = 0
                    except discord.HTTPException as e:
                        if e.status == 429:
                            await handle_rate_limit_response(
                                getattr(e, "retry_after", None)
                            )
                    await asyncio.sleep(2.0)

                    await check_status(client, channel, client.mudae_prefix)
            except Exception as e:
                log_function(t("setup_error", error=e), preset_name, "ERROR")
                await client.close()
        else:
            try:
                await check_status(
                    client, channel, client.mudae_prefix, proceed_to_rolls=False
                )
            except Exception:
                pass

    async def handle_dk_power_management(client, channel, tu_content):
        content_lower = tu_content.lower()

        dk_stock_match = re.search(
            r"\*\*(\d+)\*\*\s*\$dk\s*(?:available|disponível|disponíve(?:l|is)|no estoque)",
            content_lower,
        )
        if dk_stock_match:
            client.dk_stock_count = int(dk_stock_match.group(1))
            log_function(
                t("dk_stock", dk_stock_count=client.dk_stock_count), preset_name, "INFO"
            )
        else:
            client.dk_stock_count = 0

        if client.dk_stock_count == 0:
            return

        try:
            power_match = re.search(r"power:\s*\*\*(\d+)%\*\*", content_lower)
            consumption_match = re.search(
                r"(?:each kakera reaction consumes|cada (?:reação|botão) de kakera consume)\s*(\d+)%",
                content_lower,
            )

            if not power_match or not consumption_match:
                log_function(t("dk_parse_failed"), preset_name, "WARN")
                return

            current_power = int(power_match.group(1))
            consumption_cost = int(consumption_match.group(1))

            if current_power < consumption_cost:
                log_function(
                    t("dk_activating", current_power=current_power), preset_name, "INFO"
                )
                await safe_command_delay()
                try:
                    await channel.send(f"{client.mudae_prefix}dk")
                    client.consecutive_rate_limits = 0
                except discord.HTTPException as e:
                    if e.status == 429:
                        await handle_rate_limit_response(
                            getattr(e, "retry_after", None)
                        )
                await asyncio.sleep(2.0)
                client.dk_stock_count = max(0, client.dk_stock_count - 1)

        except Exception as e:
            log_function(t("dk_error", error=e), preset_name, "ERROR")

    async def check_status(
        client, channel, mudae_prefix, proceed_to_rolls: bool = True
    ):
        log_function(t("checking_status"), client.preset_name, "CHECK")
        tu_message_content = None
        client.current_min_kakera_for_roll_claim = client.min_kakera

        def parse_hours_minutes(match_obj):
            if not match_obj:
                return 0, 0
            groups = match_obj.groups(default="")
            h_str = groups[0] if len(groups) >= 1 else ""
            m_str = groups[1] if len(groups) >= 2 else ""

            def get_val(s):
                d = re.sub(r"\D", "", s or "")
                return int(d) if d else 0

            return get_val(h_str), get_val(m_str)

        for _ in range(5):
            await safe_command_delay()
            try:
                await channel.send(f"{mudae_prefix}tu")
                client.consecutive_rate_limits = 0
            except discord.HTTPException as e:
                if e.status == 429:
                    await handle_rate_limit_response(getattr(e, "retry_after", None))

            await asyncio.sleep(3.0)
            async for msg in channel.history(limit=10):
                if msg.author.id == TARGET_BOT_ID and msg.content:
                    c = msg.content.lower()
                    if ("rolls" in c and "claim" in c) or (
                        "rolls" in c and "casar" in c
                    ):
                        tu_message_content = msg.content
                        break
            if tu_message_content:
                break
            await asyncio.sleep(5)

        if not tu_message_content:
            log_function(t("status_response_missing"), preset_name, "ERROR")
            if client.rolling_enabled and proceed_to_rolls:
                await asyncio.sleep(1800)
            return

        if client.dk_power_management and client.rolling_enabled:
            await handle_dk_power_management(client, channel, tu_message_content)

        c_lower = tu_message_content.lower()
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        if (
            "$rt is available" in c_lower
            or "$rt está pronto" in c_lower
            or "$rt esta pronto" in c_lower
        ):
            client.rt_available = True
            log_function(t("rt_ready"), preset_name, "INFO")
        else:
            client.rt_available = False

        can_claim = False
        wait_time = 0

        claim_reset_minutes = None
        match_claim_reset = re.search(
            r"(?:next claim reset|próximo reset de casamento).*?(?:in|em)\s*\*{0,2}(\d+h)?\s*(\d+)\*{0,2}\s*min",
            c_lower,
            re.IGNORECASE,
        )
        if match_claim_reset:
            h_c, m_c = parse_hours_minutes(match_claim_reset)
            claim_reset_minutes = h_c * 60 + m_c

        claim_ready_pt = "você __pode__ se casar agora mesmo" in c_lower
        claim_ready_en = "you __can__ claim" in c_lower

        if claim_ready_en or claim_ready_pt:
            client.claim_right_available = True
            log_function(t("claim_ready"), preset_name, "INFO")
            client.current_min_kakera_for_roll_claim = effective_roll_minimum(
                client.min_kakera,
                client.snipe_ignore_min_kakera_reset,
                claim_reset_minutes,
                client.claim_right_available,
            )

            if client.snipe_ignore_min_kakera_reset:
                if claim_reset_minutes is not None and 0 <= claim_reset_minutes <= 60:
                    log_function(
                        t(
                            "reset_minimum_exception",
                            claim_reset_minutes=claim_reset_minutes,
                        ),
                        preset_name,
                        "WARN",
                    )

            if claim_reset_minutes is not None:
                client.next_claim_reset_at_utc = now_utc + datetime.timedelta(
                    minutes=claim_reset_minutes
                )
            else:
                client.next_claim_reset_at_utc = now_utc

            can_claim = True
        else:
            client.claim_right_available = False
            match_wait = re.search(
                r"(?:can't claim|falta um tempo).*?\*\*(\d+h)?\s*(\d+)\*\* min", c_lower
            )
            if match_wait:
                h, m = parse_hours_minutes(match_wait)
                wait_time = h * 60 + m
                client.claim_cooldown_until_utc = now_utc + datetime.timedelta(
                    minutes=wait_time
                )
                log_function(
                    with_statistics(
                        t("claim_cooldown", hours=h, minutes=m),
                        deadline=client.claim_cooldown_until_utc,
                    ),
                    preset_name,
                    "INFO",
                )

            immediate_roll = (
                client.rolling_enabled
                and proceed_to_rolls
                and (client.key_mode or client.rt_available)
            )
            if immediate_roll:
                can_claim = True
            elif client.rolling_enabled and proceed_to_rolls:
                await humanized_wait_and_proceed(
                    client, channel, wait_time, "reason_claim_reset"
                )
                await check_status(client, channel, mudae_prefix)
                return
            else:
                return

        if (
            "you __can__ react" in c_lower
            or "pode reagir" in c_lower
            or "pegar kakera" in c_lower
        ):
            client.kakera_react_available = True
            client.kakera_react_cooldown_until_utc = None
        elif "can't react" in c_lower or "não pode" in c_lower:
            client.kakera_react_available = False
            match_k = re.search(
                r"(?:react|pegar).*?\*\*(\d+h)?\s*(\d+)\*\* min", c_lower
            )
            if match_k:
                h, m = parse_hours_minutes(match_k)
                client.kakera_react_cooldown_until_utc = now_utc + datetime.timedelta(
                    minutes=(h * 60 + m)
                )

        if client.key_limit_hit:
            log_function(t("key_limit_recovery"), preset_name, "INFO")
            client.key_limit_hit = False
            return

        if client.rolling_enabled and proceed_to_rolls:
            await check_rolls_left_tu(
                client,
                channel,
                mudae_prefix,
                log_function,
                preset_name,
                tu_message_content,
                (client.current_min_kakera_for_roll_claim == 0),
                (
                    (client.key_mode or client.rt_available)
                    and not client.claim_right_available
                ),
            )

    async def check_rolls_left_tu(
        client,
        channel,
        mudae_prefix,
        log_function,
        preset_name,
        tu_message_content_for_rolls,
        ignore_limit_for_post_roll,
        key_mode_only_kakera_for_post_roll,
    ):
        content_lower = tu_message_content_for_rolls.lower()
        rolls_left = 0
        us_rolls_left = 0
        reset_time_r = 0

        def parse_int_from_fragment(fragment: str) -> int:
            digits = re.sub(r"[^\d]", "", fragment or "")
            return int(digits) if digits else 0

        main_match_en = re.search(
            r"you have\s+\*{0,2}([\d,.]+)\*{0,2}\s+rolls?(.*?)(?:left\b)",
            content_lower,
            re.DOTALL,
        )
        main_match_pt = re.search(
            r"você tem\s+\*{0,2}([\d,.]+)\*{0,2}\s+rolls?(.*?)(?:restantes\b)",
            content_lower,
            re.DOTALL,
        )

        main_match = main_match_en or main_match_pt

        if main_match:
            rolls_left = parse_int_from_fragment(main_match.group(1))
            middle_text = main_match.group(2)

            for bonus_match in re.finditer(
                r"\(\+\*{0,2}([\d,.]+)\*{0,2}\s+\$(us|mk)\)", middle_text
            ):
                amount = parse_int_from_fragment(bonus_match.group(1))
                bonus_type = bonus_match.group(2).lower()

                if bonus_type == "us":
                    us_rolls_left += amount

            match_reset = re.search(
                r"(?:reset in|reinicialização é em)\s+\*{0,2}(\d+h)?\*{0,2}\s*\*{0,2}(\d+)\*{0,2}\s*min",
                content_lower[main_match.end() :],
            )
            if match_reset:
                h_r = parse_int_from_fragment(match_reset.group(1))
                m_r = parse_int_from_fragment(match_reset.group(2))
                reset_time_r = h_r * 60 + m_r
            else:
                reset_time_r = 60

            total_rolls = rolls_left + us_rolls_left

            log_function(
                t(
                    "rolls_parsed",
                    total_rolls=total_rolls,
                    rolls_left=rolls_left,
                    us_rolls_left=us_rolls_left,
                    reset_time_r=reset_time_r,
                ),
                preset_name,
                "CHECK",
            )

            if total_rolls == 0:
                if reset_time_r <= 0:
                    reset_time_r = 60
                await humanized_wait_and_proceed(
                    client, channel, reset_time_r, "reason_rolls_reset"
                )
                await check_status(client, channel, mudae_prefix)
                return
            else:
                log_detail = (
                    t("roll_bonus", count=us_rolls_left) if us_rolls_left > 0 else ""
                )
                log_function(
                    t(
                        "rolls_available",
                        total_rolls=total_rolls,
                        log_detail=log_detail,
                        reset_time_r=reset_time_r,
                    ),
                    preset_name,
                    "INFO",
                )
                await start_roll_commands(
                    client,
                    channel,
                    total_rolls,
                    ignore_limit_for_post_roll,
                    key_mode_only_kakera_for_post_roll,
                )
                return
        else:
            log_function(t("roll_count_failed"), preset_name, "ERROR")
            await asyncio.sleep(30)
            await check_status(client, channel, mudae_prefix)
            return

    async def start_roll_commands(
        client,
        channel,
        rolls_left,
        ignore_limit_for_post_roll,
        key_mode_only_kakera_for_post_roll,
    ):
        log_text = t("rolling", count=rolls_left)
        log_text += t("reactive_suffix") if client.enable_reactive_self_snipe else ""
        log_function(log_text, client.preset_name, "INFO")

        start_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            seconds=0.5
        )
        client.is_actively_rolling = True
        client.interrupt_rolling = False

        try:
            for i in range(rolls_left):
                if client.interrupt_rolling:
                    break
                try:
                    await send_roll_command(channel, roll_command)
                    await asyncio.sleep(
                        max(client.roll_speed, 0.5 if client.use_slash_rolls else 0.3)
                    )
                except Exception:
                    await asyncio.sleep(2)
        finally:
            client.is_actively_rolling = False
        await asyncio.sleep(5)

        mudae_messages_to_process = []
        try:
            async for msg in channel.history(
                limit=(rolls_left * 2 + 10), after=start_time, oldest_first=False
            ):
                if msg.author.id == TARGET_BOT_ID and msg.embeds:
                    mudae_messages_to_process.append(msg)

            mudae_messages_to_process.reverse()
            if mudae_messages_to_process:
                await handle_mudae_messages(
                    client,
                    channel,
                    mudae_messages_to_process,
                    ignore_limit_for_post_roll,
                    key_mode_only_kakera_for_post_roll,
                )
        except Exception as e:
            log_function(t("post_roll_error", error=e), preset_name, "ERROR")

        await asyncio.sleep(2)
        if client.snipe_happened or client.series_snipe_happened:
            client.snipe_happened = False
            client.series_snipe_happened = False

        await asyncio.sleep(1)
        await check_status(client, channel, client.mudae_prefix)

    async def handle_mudae_messages(
        client, channel, mudae_messages, ignore_limit_param, key_mode_only_kakera_param
    ):
        kakera_claims = []
        char_claims_post = []
        wl_claims_post = []
        min_kak_post = 0 if ignore_limit_param else client.min_kakera

        for msg in mudae_messages:
            if not msg.embeds:
                continue
            embed = msg.embeds[0]
            if not is_character_embed(embed):
                continue

            all_kakera_emojis = KAKERA_EMOJIS + CHAOS_KAKERA_EMOJIS
            is_kakera = msg.components and any(
                hasattr(b, "emoji")
                and hasattr(b.emoji, "name")
                and b.emoji.name in all_kakera_emojis
                for c in msg.components
                for b in c.children
            )

            if is_kakera:
                kakera_claims.append(msg)
            elif client.claim_right_available or key_mode_only_kakera_param:
                if has_claim_option(msg, embed):
                    char_n = embed.author.name.lower()
                    desc = embed.description or ""
                    k_v = parse_kakera_value(desc)

                    is_wl = any(w == char_n for w in client.wishlist)
                    if is_wl:
                        wl_claims_post.append((msg, char_n, k_v))
                    elif meets_minimum(k_v, min_kak_post):
                        char_claims_post.append((msg, char_n, k_v))

        for msg_k in kakera_claims:
            await claim_character(client, channel, msg_k, is_kakera=True)
            await asyncio.sleep(0.5)

        claimed_post = False
        msg_claimed_id = -1

        if client.claim_right_available and is_character_snipe_allowed():
            if wl_claims_post:
                msg_c, n, v = wl_claims_post[0]
                if await claim_character(client, channel, msg_c, is_kakera=False):
                    claimed_post = True
                    client.claim_right_available = False
                    msg_claimed_id = msg_c.id
            elif char_claims_post:
                char_claims_post.sort(key=lambda x: x[2], reverse=True)
                msg_c, n, v = char_claims_post[0]
                if await claim_character(client, channel, msg_c, is_kakera=False):
                    claimed_post = True
                    client.claim_right_available = False
                    msg_claimed_id = msg_c.id

        if (key_mode_only_kakera_param or claimed_post) and client.rt_available:
            rt_targets = [i for i in wl_claims_post if i[0].id != msg_claimed_id] + [
                i for i in char_claims_post if i[0].id != msg_claimed_id
            ]
            rt_targets.sort(
                key=lambda x: x[2] if x[2] is not None else -1, reverse=True
            )
            if rt_targets:
                msg_rt, n_rt, v_rt = rt_targets[0]
                if meets_minimum(v_rt, min_kak_post):
                    log_function(
                        t("rt_attempt", character=n_rt, value=v_rt),
                        preset_name,
                        "CLAIM",
                    )
                    try:
                        await safe_command_delay()
                        await channel.send(f"{client.mudae_prefix}rt")
                        client.rt_available = False
                        client.consecutive_rate_limits = 0
                        await asyncio.sleep(1.0)
                        await claim_character(client, channel, msg_rt, is_rt_claim=True)
                    except discord.HTTPException as e:
                        if e.status == 429:
                            await handle_rate_limit_response(
                                getattr(e, "retry_after", None)
                            )
                    except Exception:
                        pass

    async def claim_character(
        client, channel, msg, is_kakera=False, is_rt_claim=False, is_snipe=False
    ):
        if not msg or not msg.embeds:
            return False
        embed = msg.embeds[0]
        char_name = embed.author.name if embed.author else t("unknown_character")

        if not is_kakera and not is_rt_claim and not is_character_snipe_allowed():
            return False

        if is_kakera:
            chaos_count = count_chaos_keys(embed)
            if not is_snipe and client.only_chaos and chaos_count == 0:
                return False

            target_list = (
                CHAOS_KAKERA_EMOJIS
                if (chaos_count > 0 and not is_snipe)
                else KAKERA_EMOJIS
            )
            cooldown_active = not is_kakera_reaction_allowed()
            clicked = False

            has_p = msg.components and any(
                hasattr(b, "emoji")
                and hasattr(b.emoji, "name")
                and b.emoji.name == "kakeraP"
                for c in msg.components
                for b in c.children
            )

            if cooldown_active and not has_p:
                return False

            if msg.components:
                for comp in msg.components:
                    for btn in comp.children:
                        if (
                            hasattr(btn, "emoji")
                            and hasattr(btn.emoji, "name")
                            and btn.emoji.name in target_list
                        ):
                            name = btn.emoji.name
                            if cooldown_active and name != "kakeraP":
                                continue
                            try:
                                await btn.click()
                                clicked = True
                                log_function(
                                    t("kakera_clicked", char_name=char_name),
                                    client.preset_name,
                                    "KAKERA",
                                )
                                await asyncio.sleep(0.5)
                            except Exception:
                                pass
            return clicked

        clicked_claim = False
        if msg.components:
            for comp in msg.components:
                if clicked_claim:
                    break
                for btn in comp.children:
                    if (
                        hasattr(btn, "emoji")
                        and hasattr(btn.emoji, "name")
                        and btn.emoji.name in CLAIM_EMOJIS
                    ):
                        try:
                            log_function(
                                t("claiming_character", char_name=char_name),
                                client.preset_name,
                                "CLAIM",
                            )
                            await btn.click()
                            clicked_claim = True
                            await asyncio.sleep(2.0)
                            client.snipe_watch[msg.id] = {
                                "char_name": char_name,
                                "ts": time.time(),
                            }
                            return True
                        except Exception:
                            return False

        if not clicked_claim and has_claim_option(msg, embed):
            try:
                log_function(
                    t("claiming_reaction", char_name=char_name),
                    client.preset_name,
                    "CLAIM",
                )
                await msg.add_reaction("💖")
                await asyncio.sleep(2.0)
                client.snipe_watch[msg.id] = {"char_name": char_name, "ts": time.time()}
                return True
            except Exception:
                return False

        return False

    async def humanized_wait_and_proceed(
        client, channel, base_reset_minutes, reason="reason_reset"
    ):
        min_wait = max(0.0, base_reset_minutes * 60)
        window = max(0.0, client.humanization_window_minutes * 60)

        if min_wait <= 0:
            min_wait = max(client.delay_seconds + 60, 240)

        wait_seconds = min_wait + (
            random.uniform(0, window) if client.humanization_enabled else 0
        )

        log_function(
            t("waiting", minutes=wait_seconds / 60, reason=t(reason)),
            preset_name,
            "RESET",
        )
        await asyncio.sleep(wait_seconds)

        if client.humanization_enabled:
            while True:
                try:
                    last_msg = None
                    async for m in channel.history(limit=1):
                        last_msg = m

                    if not last_msg:
                        break

                    diff = (
                        datetime.datetime.now(timezone.utc) - last_msg.created_at
                    ).total_seconds()
                    if diff >= client.humanization_inactivity_seconds:
                        break
                    else:
                        await asyncio.sleep(
                            client.humanization_inactivity_seconds - diff + 0.5
                        )
                except Exception:
                    break

    @client.event
    async def on_message(message):
        if (
            message.author.id != TARGET_BOT_ID
            or message.channel.id != client.target_channel_id
        ):
            if client.rolling_enabled:
                await client.process_commands(message)
            return

        if client.target_guild_id and message.guild.id != client.target_guild_id:
            return

        if not message.embeds:
            return
        embed = message.embeds[0]

        # Handle Pokeslot results
        if client.auto_pokeslot_enabled and client.pokeslot_running:
            content = message.content.lower()
            if "pokeslot" in content:
                cooldown_match = re.search(
                    r"available in\s+\*\*(\d+)h\s*(\d+)\*\*", content
                )
                if cooldown_match:
                    hours = int(cooldown_match.group(1))
                    minutes = int(cooldown_match.group(2))
                    cooldown_minutes = hours * 60 + minutes
                    client.pokeslot_cooldown_until_utc = datetime.datetime.now(
                        datetime.timezone.utc
                    ) + datetime.timedelta(minutes=cooldown_minutes)
                    log_function(
                        t("pokeslot_cooldown", hours=hours, minutes=minutes),
                        preset_name,
                        "POKESLOT",
                    )

                result_match = re.search(r"won\s+\*\*(\d+)\*\*|perdeu|lost", content)
                if result_match:
                    if "won" in content or "ganhou" in content:
                        amount = result_match.group(1) if result_match.group(1) else "0"
                        log_function(
                            t("pokeslot_win", amount=amount), preset_name, "POKESLOT"
                        )
                    else:
                        log_function(t("pokeslot_loss"), preset_name, "POKESLOT")

                client.pokeslot_running = False
                return

        # Handle Kakera Drops (non-character messages)
        if not is_character_embed(embed):
            if (
                client.kakera_reaction_snipe_mode_active
                and message.id not in client.kakera_reaction_sniped_messages
            ):
                all_k = KAKERA_EMOJIS + CHAOS_KAKERA_EMOJIS
                has_btn = message.components and any(
                    hasattr(b, "emoji")
                    and hasattr(b.emoji, "name")
                    and b.emoji.name in all_k
                    for c in message.components
                    for b in c.children
                )

                if has_btn:
                    if client.kakera_reaction_snipe_targets:
                        owner = get_character_owner(embed)
                        if (
                            not owner
                            or owner not in client.kakera_reaction_snipe_targets
                        ):
                            return

                    client.kakera_reaction_sniped_messages.add(message.id)
                    await asyncio.sleep(client.kakera_reaction_snipe_delay_value)
                    await claim_character(
                        client, message.channel, message, is_kakera=True, is_snipe=True
                    )
            return

        # ==================== CHARACTER EMBED ====================
        # Get character info ONCE at the start
        char_name = embed.author.name.lower() if embed.author else ""
        desc = embed.description or ""

        # Extract series name (more robust)
        series = ""
        if desc:
            # Try first line (most common)
            first_line = desc.splitlines()[0] if desc.splitlines() else ""
            series = first_line.lower()

            # Fallback: look for series pattern in entire description
            if not series:
                series_match = re.search(r"\*\*(.+?)\*\*", desc)
                if series_match:
                    series = series_match.group(1).lower()

        # Extract kakera value
        kakera_value = parse_kakera_value(desc)

        # Check if character has claim option
        has_claim = has_claim_option(message, embed)

        # Key Limit Check
        if client.rolling_enabled and client.is_actively_rolling:
            if "limit of 1,000 keys" in desc or "limite de 1.000 chaves" in desc:
                client.interrupt_rolling = True
                client.key_limit_hit = True
                log_function(t("key_limit_hit"), preset_name, "ERROR")
                await asyncio.sleep(3600 + random.randint(0, 600))
                await check_status(client, message.channel, client.mudae_prefix)
                return

        # ==================== PRIORITY 1: REACTIVE SELF-SNIPE (during own rolls) ====================
        if (
            client.rolling_enabled
            and client.enable_reactive_self_snipe
            and client.is_actively_rolling
        ):
            if client.claim_right_available and has_claim:
                # Check wishlist
                is_wishlist = char_name in client.wishlist

                # Check series wishlist
                is_series_wishlist = False
                if client.series_wishlist and series:
                    is_series_wishlist = any(
                        s in series for s in client.series_wishlist
                    )

                # Check value threshold
                is_value_target = reactive_value_target(
                    kakera_value,
                    client.kakera_snipe_mode_active,
                    client.kakera_snipe_threshold,
                    client.current_min_kakera_for_roll_claim,
                )

                should_claim = is_wishlist or is_series_wishlist or is_value_target

                if should_claim:
                    if client.reactive_snipe_delay > 0:
                        await asyncio.sleep(client.reactive_snipe_delay)

                    if await claim_character(client, message.channel, message):
                        client.claim_right_available = False
                        client.interrupt_rolling = True
                        client.snipe_happened = True

                        claim_reason = (
                            t("reason_wishlist")
                            if is_wishlist
                            else (
                                t("reason_series")
                                if is_series_wishlist
                                else t("reason_value")
                            )
                        )
                        log_function(
                            t(
                                "reactive_claim",
                                claim_reason=claim_reason,
                                char_name=char_name,
                                series=series,
                                kakera_value=(
                                    kakera_value
                                    if kakera_value is not None
                                    else t("unknown_value")
                                ),
                            ),
                            preset_name,
                            "CLAIM",
                        )

                        # Still process kakera on this message
                        all_k = KAKERA_EMOJIS + CHAOS_KAKERA_EMOJIS
                        if any(
                            hasattr(b, "emoji")
                            and hasattr(b.emoji, "name")
                            and b.emoji.name in all_k
                            for c in message.components
                            for b in c.children
                        ):
                            await asyncio.sleep(0.5)
                            await claim_character(
                                client, message.channel, message, is_kakera=True
                            )

                        return

        # ==================== PRIORITY 2: AUTO-STEAL (when NOT rolling) ====================
        if not client.is_actively_rolling and client.auto_steal_enabled:
            if message.id not in client.steal_sniped_messages and has_claim:
                # Check wishlist
                is_steal_wl = char_name in client.wishlist

                # Check series wishlist
                is_steal_series = False
                if client.series_wishlist and series:
                    is_steal_series = any(s in series for s in client.series_wishlist)

                should_steal = is_steal_wl or is_steal_series

                if should_steal:
                    client.steal_sniped_messages.add(message.id)
                    log_function(
                        t(
                            "steal_target",
                            char_name=char_name,
                            series=series,
                            kakera_value=(
                                kakera_value
                                if kakera_value is not None
                                else t("unknown_value")
                            ),
                        ),
                        preset_name,
                        "STEAL",
                    )

                    await asyncio.sleep(client.steal_delay)

                    if await claim_character(client, message.channel, message):
                        log_function(
                            t("steal_success", char_name=char_name),
                            preset_name,
                            "STEAL",
                        )
                        return

        # ==================== PRIORITY 3: EXTERNAL SNIPE (other users' rolls) ====================
        if not client.is_actively_rolling:
            # External Kakera Snipe on Character Rolls
            if (
                client.kakera_reaction_snipe_mode_active
                and message.id not in client.kakera_reaction_sniped_messages
            ):
                all_k = KAKERA_EMOJIS + CHAOS_KAKERA_EMOJIS
                has_btn = message.components and any(
                    hasattr(b, "emoji")
                    and hasattr(b.emoji, "name")
                    and b.emoji.name in all_k
                    for c in message.components
                    for b in c.children
                )

                if has_btn:
                    target_ok = True
                    if client.kakera_reaction_snipe_targets:
                        owner = get_character_owner(embed)
                        if (
                            not owner
                            or owner not in client.kakera_reaction_snipe_targets
                        ):
                            target_ok = False

                    if target_ok:
                        client.kakera_reaction_sniped_messages.add(message.id)
                        await asyncio.sleep(client.kakera_reaction_snipe_delay_value)
                        await claim_character(
                            client,
                            message.channel,
                            message,
                            is_kakera=True,
                            is_snipe=True,
                        )
                        return

            # Series Snipe (HIGH PRIORITY)
            if client.series_snipe_mode and client.series_wishlist and has_claim:
                if series and any(s in series for s in client.series_wishlist):
                    log_function(
                        t("series_trigger", char_name=char_name, series=series),
                        preset_name,
                        "INFO",
                    )
                    await asyncio.sleep(client.series_snipe_delay)

                    if await claim_character(client, message.channel, message):
                        client.series_snipe_happened = True
                        log_function(
                            t("series_success", char_name=char_name, series=series),
                            preset_name,
                            "CLAIM",
                        )
                        return

            # Character Wishlist Snipe
            if client.snipe_mode and char_name in client.wishlist and has_claim:
                log_function(
                    t("wishlist_trigger", char_name=char_name), preset_name, "INFO"
                )
                await asyncio.sleep(client.snipe_delay)

                if await claim_character(client, message.channel, message):
                    client.snipe_happened = True
                    log_function(
                        t("wishlist_success", char_name=char_name), preset_name, "CLAIM"
                    )
                    return

            # Value Snipe
            if client.kakera_snipe_mode_active and has_claim:
                if meets_minimum(kakera_value, client.kakera_snipe_threshold):
                    log_function(
                        t(
                            "value_trigger",
                            char_name=char_name,
                            kakera_value=(
                                kakera_value
                                if kakera_value is not None
                                else t("unknown_value")
                            ),
                        ),
                        preset_name,
                        "INFO",
                    )
                    await asyncio.sleep(client.snipe_delay)

                    if await claim_character(client, message.channel, message):
                        client.snipe_happened = True
                        log_function(
                            t(
                                "value_success",
                                char_name=char_name,
                                kakera_value=(
                                    kakera_value
                                    if kakera_value is not None
                                    else t("unknown_value")
                                ),
                            ),
                            preset_name,
                            "CLAIM",
                        )
                        return

        # ==================== PRIORITY 4: REACTIVE KAKERA (during own rolls) ====================
        if (
            client.rolling_enabled
            and client.enable_reactive_self_snipe
            and client.is_actively_rolling
        ):
            all_k = KAKERA_EMOJIS + CHAOS_KAKERA_EMOJIS
            if any(
                hasattr(b, "emoji")
                and hasattr(b.emoji, "name")
                and b.emoji.name in all_k
                for c in message.components
                for b in c.children
            ):
                await claim_character(client, message.channel, message, is_kakera=True)

    @client.event
    async def on_message_edit(before, after):
        if after.id not in client.snipe_watch:
            return
        if not after.embeds:
            return

        embed = after.embeds[0]
        ft = (embed.footer.text or "").lower()
        if "belongs to" not in ft and "pertence a" not in ft:
            return

        watch = client.snipe_watch.pop(after.id)
        name = watch["char_name"]

        user_names = [client.user.name.lower(), client.user.display_name.lower()]
        if client.user.global_name:
            user_names.append(client.user.global_name.lower())

        if any(n in ft for n in user_names):
            client.claim_right_available = False
            client.next_claim_reset_at_utc = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(hours=3)
            client.claim_cooldown_until_utc = client.next_claim_reset_at_utc
            log_function(
                with_statistics(
                    t("snipe_confirmed", name=name),
                    confirmation=after.id,
                    deadline=client.claim_cooldown_until_utc,
                ),
                preset_name,
                "CLAIM",
            )
        else:
            log_function(t("snipe_failed", name=name), preset_name, "INFO")

    try:
        client.run(token)
    except Exception as e:
        log_function(
            t("client_crash", BOT_NAME=BOT_NAME, error=e), preset_name, "ERROR"
        )
