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
            stats=stats,
            recent_events=recent_events,
            DurationFormatter=DurationFormatter
        )

    @bp.route('/history')
    def history():
        from flask import request, jsonify
        days = int(request.args.get('days', 30))
        history_data = stats_service.get_daily_history(days)
        return jsonify(history_data)

    @bp.route('/app')
    @bp.route('/app/<location_id>')
    def webapp(location_id=None):
        loc = (location_id or '').lower()
        if loc in ['kyiv', 'kiev', 'home', '']:
            loc = 'home'
        elif loc in ['vinnytsia', 'vinnitsa', 'vn']:
            loc = 'vinnytsia'
        return render_template('webapp.html', initial_location=loc)

    return bp
