from flask import Blueprint, render_template
from light_bot.services.stats_service import StatsService
from light_bot.formatters.duration_formatter import DurationFormatter

def create_stats_blueprint(stats_service: StatsService):
    bp = Blueprint('stats', __name__, template_folder='../templates')

    @bp.route('/')
    def index():
        stats = stats_service.get_stats()
        recent_events = stats_service.get_recent_events()
        
        return render_template(
            'stats.html',
            total_outages=stats.get('total_outages', 0),
            total_duration=DurationFormatter.format_duration(stats.get('total_outage_duration')),
            last_24h_duration=DurationFormatter.format_duration(stats.get('last_24h_outage_duration')),
            recent_events=recent_events
        )

    return bp
