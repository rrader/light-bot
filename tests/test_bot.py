import pytest
import asyncio
import os
import tempfile
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from telegram.error import TelegramError
import sys

# Add parent directory to path to import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot import TelegramChannelBot


@pytest.fixture
def temp_files():
    """Create temporary files for testing"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_power.txt') as power_file:
        power_status_file = power_file.name
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_last.txt') as last_file:
        last_status_file = last_file.name

    yield power_status_file, last_status_file

    # Cleanup
    try:
        os.unlink(power_status_file)
    except:
        pass
    try:
        os.unlink(last_status_file)
    except:
        pass


@pytest.fixture
def bot():
    """Create a bot instance with mocked Telegram Bot"""
    with patch('bot.Bot') as mock_bot:
        bot_instance = TelegramChannelBot()
        bot_instance.bot = Mock()
        return bot_instance


class TestTelegramChannelBot:
    """Tests for TelegramChannelBot class"""

    def test_initialization(self, bot):
        """Test bot initializes correctly"""
        assert bot.bot is not None
        assert bot.channel_id == '@test_channel'

    @pytest.mark.asyncio
    async def test_send_message_success(self, bot):
        """Test successful message sending"""
        # Mock send_message to return a message object
        mock_message = Mock()
        mock_message.message_id = 123
        bot.bot.send_message = AsyncMock(return_value=mock_message)

        result = await bot.send_message("Test message")

        assert result is True
        bot.bot.send_message.assert_called_once_with(
            chat_id='@test_channel',
            text="Test message",
            parse_mode='HTML'
        )

    @pytest.mark.asyncio
    async def test_send_message_failure(self, bot):
        """Test message sending failure"""
        bot.bot.send_message = AsyncMock(side_effect=TelegramError("Network error"))

        result = await bot.send_message("Test message")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_photo_success(self, bot):
        """Test successful photo sending"""
        mock_message = Mock()
        mock_message.message_id = 456
        bot.bot.send_photo = AsyncMock(return_value=mock_message)

        result = await bot.send_photo("https://example.com/photo.jpg", "Caption")

        assert result is True
        bot.bot.send_photo.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_document_success(self, bot):
        """Test successful document sending"""
        mock_message = Mock()
        mock_message.message_id = 789
        bot.bot.send_document = AsyncMock(return_value=mock_message)

        result = await bot.send_document("https://example.com/doc.pdf", "Document")

        assert result is True
        bot.bot.send_document.assert_called_once()

