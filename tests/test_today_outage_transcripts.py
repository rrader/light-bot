"""Regression replays for the real 2026-11-05 Kyiv and Vinnytsia outages."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from light_bot.models import LocationConfig
from light_bot.services import outage_alert_manager as outage_module
from light_bot.services import unstable_alert_manager as unstable_module


KYIV = ZoneInfo("Europe/Kyiv")
AUTH = {"Authorization": "Bearer test_api_token_123"}


def at(value):
    return datetime.fromisoformat(value).astimezone(KYIV)


class ManualTimer:
    """A deterministic timer that tests can fire at the recorded event time."""

    instances = []
    clock = None

    def __init__(self, interval, function, args=(), kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs or {}
        self.cancelled = False
        self.started = False
        self.instances.append(self)

    def start(self):
        self.started = True
        self.started_at = self.clock.current if self.clock else None

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.started = False
            self.function(*self.args, **self.kwargs)


class EventLedger:
    """Small in-memory stand-in for the production event and voltage tables."""

    def __init__(self):
        self.events = []
        self.readings = []
        self.pending_stabilization = {}

    def record_reading(self, **data):
        if data.get("voltage") is not None:
            self.readings.append(data)

    def record_event(self, **data):
        self.events.append(SimpleNamespace(**data))
        self.events.sort(key=lambda event: event.timestamp, reverse=True)

    def get_recent_events(self, limit=20, location=None):
        return [e for e in self.events if e.location == location][:limit]

    def count_events(self, location, status, since=None):
        return sum(
            1 for event in self.events
            if event.location == location
            and event.status == status
            and (since is None or event.timestamp >= since)
        )

    def get_voltage_extrema(self, location, since=None):
        values = [
            reading["voltage"] for reading in self.readings
            if reading["location"] == location
            and reading["voltage"] is not None
            and (since is None or reading["timestamp"] >= since)
        ]
        return (min(values), max(values)) if values else (None, None)

    def save_pending_stabilization_alert(
        self, location, recovery_timestamp, due_timestamp, voltage, min_voltage, max_voltage
    ):
        self.pending_stabilization[location] = {
            "location": location,
            "recovery_timestamp": recovery_timestamp,
            "due_timestamp": due_timestamp,
            "voltage": voltage,
            "min_voltage": min_voltage,
            "max_voltage": max_voltage,
        }
        return True

    def get_pending_stabilization_alerts(self):
        return list(self.pending_stabilization.values())

    def is_current_stabilization(self, location, recovery_timestamp):
        current = next((event for event in self.events if event.location == location), None)
        return bool(
            current and current.status == "on" and current.timestamp == recovery_timestamp
        )

    def remove_pending_stabilization_alert(self, location):
        self.pending_stabilization.pop(location, None)


@pytest.fixture
def replay(monkeypatch, tmp_path):
    from light_bot.core import server

    ManualTimer.instances = []
    monkeypatch.setattr(unstable_module.threading, "Timer", ManualTimer)
    monkeypatch.setattr(outage_module.threading, "Timer", ManualTimer)

    clock = SimpleNamespace(current=None)
    ManualTimer.clock = clock
    monkeypatch.setattr(server, "_now", lambda: clock.current)
    monkeypatch.setattr(unstable_module, "_now", lambda: clock.current)
    monkeypatch.setattr(server, "find_next_outage_for_group", lambda _group: None)

    bot = MagicMock()
    bot.channel_id = "@kyiv_test_channel"
    bot.send_message = AsyncMock(return_value=True)
    ledger = EventLedger()
    locations = {
        "home": LocationConfig(
            id="home", name="Дім", status_file=str(tmp_path / "home.txt"),
            channel_id="@kyiv_test_channel", yasno_group=None
        ),
        "vinnytsia": LocationConfig(
            id="vinnytsia", name="Вінниця", status_file=str(tmp_path / "vinnytsia.txt"),
            channel_id="@vinnytsia_test_channel", yasno_group=None
        ),
    }

    monkeypatch.setattr(server, "get_location_config", lambda location_id: locations.get(location_id or "home"))
    monkeypatch.setattr(server, "LOCATIONS", locations)
    monkeypatch.setattr(server, "WATCHDOG_STATUS_FILE", locations["home"].status_file)
    monkeypatch.setattr(server, "stats_service", ledger)
    monkeypatch.setattr(server, "telegram_bot", bot)
    monkeypatch.setattr(
        server,
        "unstable_alert_manager",
        unstable_module.UnstableAlertManager(
            delay_seconds=180,
            telegram_bot=bot,
            stats_service=ledger,
            frequent_threshold=3,
            frequent_window_seconds=3600,
            frequent_cooldown_seconds=7200,
            stabilization_seconds=3600,
        ),
    )
    monkeypatch.setattr(
        server,
        "outage_alert_manager",
        outage_module.OutageAlertManager(delay_seconds=40, telegram_bot=bot),
    )
    server.app.config["TESTING"] = True
    return SimpleNamespace(
        server=server,
        clock=clock,
        bot=bot,
        ledger=ledger,
        locations=locations,
        client=server.app.test_client(),
        timers=ManualTimer.instances,
    )


def seed_state(replay, location_id, status, timestamp, **fields):
    location = replay.locations[location_id]
    voltage = fields.get("voltage")
    lines = [status, f"Last updated: {timestamp.isoformat()}"]
    if voltage is not None:
        lines.append(f"Voltage: {voltage}")
    with open(location.status_file, "w") as state_file:
        state_file.write("\n".join(lines) + "\n")
    replay.ledger.record_event(
        status=status,
        timestamp=timestamp,
        location=location_id,
        voltage=voltage,
        source=fields.get("source"),
        before_relay=fields.get("before_relay"),
        after_relay=fields.get("after_relay"),
    )


def post_status(replay, location_id, timestamp, status, **fields):
    replay.clock.current = timestamp
    response = replay.client.post(
        f"/power-status/{location_id}",
        headers=AUTH,
        json={"status": status, **fields},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["status_changed"] is True
    return response.json


def sent_messages(replay):
    return [call.args[0] for call in replay.bot.send_message.call_args_list]


def advance_to(replay, timestamp):
    """Run pending timers at their real due instants while advancing the replay clock."""
    while True:
        due = [
            timer for timer in replay.timers
            if timer.started and not timer.cancelled
            and getattr(timer, "started_at", None) is not None
            and timer.started_at + timedelta(seconds=timer.interval) <= timestamp
        ]
        if not due:
            break
        timer = min(due, key=lambda item: item.started_at + timedelta(seconds=item.interval))
        replay.clock.current = timer.started_at + timedelta(seconds=timer.interval)
        timer.fire()
    replay.clock.current = timestamp


def test_vinnytsia_replays_off_to_on_without_voltage_telemetry(replay):
    """The no-relay source still sends outage and restoration messages without fake volts."""
    seed_state(
        replay, "vinnytsia", "on", at("2026-11-05T00:15:44.179847+02:00"),
        source=None,
    )

    off = post_status(
        replay, "vinnytsia", at("2026-11-05T02:03:20.572154+02:00"), "off"
    )
    # Outage notification is debounced; it is sent by the timer, not the request.
    assert off["notification_sent"] is False
    outage_timer = next(t for t in replay.timers if t.interval == 40)
    replay.clock.current = at("2026-11-05T02:04:00.572154+02:00")
    outage_timer.fire()

    on = post_status(
        replay, "vinnytsia", at("2026-11-05T04:03:15.873032+02:00"), "on"
    )
    assert on["notification_sent"] is True

    messages = sent_messages(replay)
    assert len(messages) == 2
    assert "Світло зникло (Вінниця)" in messages[0]
    assert "05.11.2026 02:03:20" in messages[0]
    assert "Світло з'явилось (Вінниця)" in messages[1]
    assert "05.11.2026 04:03:15" in messages[1]
    assert "1 година 59 хвилин" in messages[1]
    assert "Напруга в мережі" not in messages[0] + messages[1]
    assert all(
        call.kwargs.get("chat_id") == "@vinnytsia_test_channel"
        for call in replay.bot.send_message.call_args_list
    )


def test_kyiv_replays_outage_short_relay_delay_and_later_sustained_instability(replay):
    """Replay today's relay timeline and inspect each message sent to the Kyiv channel."""
    seed_state(
        replay, "home", "on", at("2026-11-04T19:33:20.324232+02:00"),
        voltage=257.0, before_relay=True, after_relay=True, source="ha",
    )

    post_status(replay, "home", at("2026-11-04T23:37:20.111990+02:00"), "off", voltage=0.0)
    outage_timer = next(t for t in replay.timers if t.interval == 40)
    replay.clock.current = at("2026-11-04T23:38:00.111990+02:00")
    outage_timer.fire()

    # Power returned through a 20-second relay transition after 3h56m20s off.
    post_status(
        replay, "home", at("2026-11-05T03:33:40.116042+02:00"), "unstable",
        voltage=0.0, before_relay=True, after_relay=False, source="ha",
    )
    short_unstable_timer = next(t for t in replay.timers if t.interval == 180)
    restored = post_status(
        replay, "home", at("2026-11-05T03:34:00.117174+02:00"), "on",
        voltage=0.0, before_relay=True, after_relay=True, source="ha",
    )
    assert restored["notification_sent"] is True
    assert short_unstable_timer.cancelled is True

    # A separate sustained instability began at 04:21:20 and recovered at 04:25:40.
    replay.ledger.record_reading(
        timestamp=at("2026-11-05T04:22:00.120703+02:00"),
        location="home", voltage=262.0,
    )
    replay.ledger.record_reading(
        timestamp=at("2026-11-05T04:23:00.120703+02:00"),
        location="home", voltage=272.0,
    )
    post_status(
        replay, "home", at("2026-11-05T04:21:20.120703+02:00"), "unstable",
        voltage=271.0, before_relay=True, after_relay=False, source="ha",
    )
    sustained_timer = next(
        timer for timer in replay.timers if timer.interval == 180 and not timer.cancelled
    )
    replay.clock.current = at("2026-11-05T04:24:20.120703+02:00")
    sustained_timer.fire()

    recovered = post_status(
        replay, "home", at("2026-11-05T04:25:40.128139+02:00"), "on",
        voltage=253.0, before_relay=True, after_relay=True, source="ha",
    )
    assert recovered["notification_sent"] is False
    stable_timer = next(t for t in replay.timers if t.interval == 3600)
    assert stable_timer.started is True

    messages_before_stability = sent_messages(replay)
    assert len(messages_before_stability) == 3
    assert "Світло зникло" in messages_before_stability[0]
    assert "05.11.2026 03:34:00" in messages_before_stability[1]
    assert "Світло з'явилось!" in messages_before_stability[1]
    assert "0.0 В" not in messages_before_stability[1]
    assert "Відключення тривало" in messages_before_stability[1]
    assert "В мережі нестабільна напруга!" in messages_before_stability[2]
    assert "05.11.2026 04:21:20" in messages_before_stability[2]
    assert "272.0 В" in messages_before_stability[2]
    assert "262.0–272.0 В" in messages_before_stability[2]

    # The recovery notice is sent only after an uninterrupted hour in the on state.
    replay.clock.current = at("2026-11-05T05:25:40.128139+02:00")
    stable_timer.fire()
    messages_after_stability = sent_messages(replay)
    assert len(messages_after_stability) == 4
    assert "Напруга стабілізувалась!" in messages_after_stability[3]
    assert "05.11.2026 05:25:40" in messages_after_stability[3]
    assert all(
        call.kwargs.get("chat_id") in (None, "@kyiv_test_channel")
        for call in replay.bot.send_message.call_args_list
    )


def test_vinnytsia_replays_all_production_events_from_2026_11_04(replay):
    """Replay every Vinnytsia transition recorded in the production DB on Nov 4."""
    seed_state(replay, "vinnytsia", "on", at("2026-11-03T10:02:19.828161+02:00"))
    events = [
        ("2026-11-04T01:53:41.643985+02:00", "off"),
        ("2026-11-04T06:09:43.320270+02:00", "on"),
        ("2026-11-04T07:12:12.157756+02:00", "off"),
        ("2026-11-04T07:18:42.789780+02:00", "on"),
        ("2026-11-04T18:42:17.363499+02:00", "off"),
        ("2026-11-04T18:42:39.131832+02:00", "on"),
        ("2026-11-04T18:45:06.355346+02:00", "off"),
        ("2026-11-04T21:57:32.937853+02:00", "on"),
    ]

    for time, status in events:
        timestamp = at(time)
        advance_to(replay, timestamp)
        post_status(replay, "vinnytsia", timestamp, status)

    # The final outage notification is due 40 seconds after the final off transition.
    advance_to(replay, at("2026-11-04T21:57:33+02:00"))
    messages = sent_messages(replay)
    assert len(messages) == 6
    assert [
        "off" if "Світло зникло (Вінниця)" in message else "on"
        for message in messages
    ] == ["off", "on", "off", "on", "off", "on"]
    assert "04.11.2026 01:53:41" in messages[0]
    assert "04.11.2026 06:09:43" in messages[1]
    assert "4 години 16 хвилин" in messages[1]
    assert "04.11.2026 07:12:12" in messages[2]
    assert "04.11.2026 07:18:42" in messages[3]
    assert "04.11.2026 18:45:06" in messages[4]
    assert "04.11.2026 21:57:32" in messages[5]
    assert "3 години 12 хвилин" in messages[5]
    assert all("Напруга в мережі" not in message for message in messages)
    assert all(call.kwargs.get("chat_id") == "@vinnytsia_test_channel"
               for call in replay.bot.send_message.call_args_list)


def test_kyiv_replays_all_production_events_from_2026_11_04(replay):
    """Replay Kyiv relay and outage transitions, including suppressed short spikes."""
    seed_state(
        replay, "home", "off", at("2026-11-03T18:12:00.450010+02:00"),
        voltage=0.0, before_relay=False, after_relay=False, source="ha",
    )
    events = [
        ("2026-11-04T06:44:19.881337+02:00", "unstable", 242.0, True, False),
        ("2026-11-04T06:45:00.505210+02:00", "on", 243.0, True, True),
        ("2026-11-04T08:43:54.530888+02:00", "off", 0.0, False, False),
        ("2026-11-04T08:44:18.308742+02:00", "on", 246.0, True, True),
        ("2026-11-04T11:36:40.452999+02:00", "off", 0.0, False, False),
        ("2026-11-04T11:45:00.456819+02:00", "unstable", 248.0, True, False),
        ("2026-11-04T11:45:20.459667+02:00", "on", 247.0, True, True),
        ("2026-11-04T19:33:00.324161+02:00", "unstable", 257.0, True, False),
        ("2026-11-04T19:33:20.324232+02:00", "on", 257.0, True, True),
        ("2026-11-04T23:37:20.111990+02:00", "off", 0.0, False, False),
    ]

    for time, status, voltage, before, after in events:
        timestamp = at(time)
        advance_to(replay, timestamp)
        post_status(
            replay, "home", timestamp, status, voltage=voltage,
            before_relay=before, after_relay=after, source="ha",
        )
    advance_to(replay, at("2026-11-04T23:38:00.111990+02:00"))

    messages = sent_messages(replay)
    # The opening outage predates the replay, followed by two later outage notices and two restorations;
    # the 24-second outage and two 20-second relay trips stay silent.
    assert len(messages) == 4
    assert "Світло з'явилось!" in messages[0]
    assert "04.11.2026 06:45:00" in messages[0]
    assert "12 годин 33 хвилини" in messages[0]
    assert "0.0 В" not in messages[0]
    assert "04.11.2026 11:36:40" in messages[1]
    assert "Світло з'явилось!" in messages[2]
    assert "04.11.2026 11:45:20" in messages[2]
    assert "Відключення тривало" in messages[2]
    assert "04.11.2026 23:37:20" in messages[3]
    assert all(call.kwargs.get("chat_id") in (None, "@kyiv_test_channel")
               for call in replay.bot.send_message.call_args_list)


def test_stabilization_deadline_survives_restart_and_resumes_remaining_time(replay, monkeypatch):
    """A container restart during the stable hour restores the original deadline."""
    recovery = at("2026-11-05T04:25:40.128139+02:00")
    seed_state(
        replay, "home", "on", at("2026-11-05T03:34:00.117174+02:00"),
        voltage=253.0, before_relay=True, after_relay=True, source="ha",
    )
    unstable_start = at("2026-11-05T04:21:20.120703+02:00")
    post_status(
        replay, "home", unstable_start, "unstable", voltage=271.0,
        before_relay=True, after_relay=False, source="ha",
    )
    replay.ledger.record_reading(
        timestamp=at("2026-11-05T04:22:00.120703+02:00"), location="home", voltage=262.0
    )
    replay.server.unstable_alert_manager.record_voltage("home", 262.0)
    replay.ledger.record_reading(
        timestamp=at("2026-11-05T04:23:00.120703+02:00"), location="home", voltage=272.0
    )
    replay.server.unstable_alert_manager.record_voltage("home", 272.0)
    unstable_timer = next(t for t in replay.timers if t.interval == 180)
    replay.clock.current = at("2026-11-05T04:24:20.120703+02:00")
    unstable_timer.fire()
    post_status(
        replay, "home", recovery, "on", voltage=253.0,
        before_relay=True, after_relay=True, source="ha",
    )
    assert replay.ledger.pending_stabilization["home"]["due_timestamp"] == at(
        "2026-11-05T05:25:40.128139+02:00"
    )

    # Simulate a restart at 04:37:43; a fresh manager reconstructs the timer from SQLite.
    replay.clock.current = at("2026-11-05T04:37:43+02:00")
    for old_timer in replay.timers:
        old_timer.cancel()
    restarted_manager = unstable_module.UnstableAlertManager(
        delay_seconds=180,
        telegram_bot=replay.bot,
        stats_service=replay.ledger,
        stabilization_seconds=3600,
    )
    monkeypatch.setattr(replay.server, "unstable_alert_manager", restarted_manager)
    restarted_manager.restore_pending_stabilization_alerts(replay.locations)
    restored_timer = replay.timers[-1]
    assert restored_timer.interval == pytest.approx(2877.128139)
    assert restored_timer.started is True

    replay.clock.current = at("2026-11-05T05:25:40.128139+02:00")
    restored_timer.fire()
    assert "Напруга стабілізувалась!" in sent_messages(replay)[-1]
    assert "05.11.2026 05:25:40" in sent_messages(replay)[-1]
    assert "253.0–272.0 В" in sent_messages(replay)[-1]
    assert "home" not in replay.ledger.pending_stabilization


def test_new_instability_cancels_persisted_stabilization_after_restart(replay, monkeypatch):
    """An unstable event invalidates both a restored timer and its persisted deadline."""
    recovery = at("2026-11-05T04:25:40.128139+02:00")
    seed_state(
        replay, "home", "unstable", at("2026-11-05T04:21:20.120703+02:00"),
        voltage=271.0, before_relay=True, after_relay=False, source="ha",
    )
    post_status(
        replay, "home", recovery, "on", voltage=253.0,
        before_relay=True, after_relay=True, source="ha",
    )
    replay.clock.current = at("2026-11-05T04:40:00+02:00")
    for old_timer in replay.timers:
        old_timer.cancel()
    restarted_manager = unstable_module.UnstableAlertManager(
        delay_seconds=180, telegram_bot=replay.bot, stats_service=replay.ledger,
        stabilization_seconds=3600,
    )
    monkeypatch.setattr(replay.server, "unstable_alert_manager", restarted_manager)
    restarted_manager.restore_pending_stabilization_alerts(replay.locations)
    timer = replay.timers[-1]

    post_status(
        replay, "home", at("2026-11-05T04:40:01+02:00"), "unstable",
        voltage=260.0, before_relay=True, after_relay=False, source="ha",
    )
    assert timer.cancelled is True
    assert "home" not in replay.ledger.pending_stabilization
    replay.clock.current = at("2026-11-05T05:25:40.128139+02:00")
    timer.fire()
    assert all("Напруга стабілізувалась!" not in message for message in sent_messages(replay))
