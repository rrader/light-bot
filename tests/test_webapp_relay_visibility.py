from pathlib import Path


def test_webapp_shows_relay_only_when_source_has_both_relay_readings():
    template = Path(__file__).parents[1] / "src/light_bot/templates/webapp.html"
    source = template.read_text(encoding="utf-8")

    assert 'id="relayPill" style="display: none;"' in source
    assert 'id="relaySeparatorBefore" style="display: none;"' in source
    assert 'id="relaySeparatorAfter" style="display: none;"' in source
    assert "statusInfo.before_relay !== undefined && statusInfo.before_relay !== null" in source
    assert "statusInfo.after_relay !== undefined && statusInfo.after_relay !== null" in source
    assert "relayPill.style.display = hasRelayTelemetry ? '' : 'none'" in source
    assert "status === 'on' ? 'норма'" not in source
