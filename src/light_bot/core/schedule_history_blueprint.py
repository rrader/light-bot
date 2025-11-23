from flask import Blueprint, jsonify
from light_bot.services.stats_service import StatsService

def create_schedule_history_blueprint(stats_service: StatsService) -> Blueprint:
    schedule_history_blueprint = Blueprint('schedule_history', __name__)

    @schedule_history_blueprint.route('/schedule-history/<group_id>', methods=['GET'])
    def get_schedule_history(group_id: str):
        """Get schedule history for a group"""
        try:
            history = stats_service.get_schedule_history(group_id)
            return jsonify([h.__dict__ for h in history]), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return schedule_history_blueprint
