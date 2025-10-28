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
        assert bot.channel_id == '@test_channel'
        assert bot.last_status is None
        assert bot.monitoring is False

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

    def test_read_power_status_file_exists(self, bot, temp_files):
        """Test reading power status from existing file"""
        power_file, _ = temp_files

        with open(power_file, 'w') as f:
            f.write("on\n")
            f.write("Last updated: 2025-10-25T12:00:00\n")

        with patch('bot.WATCHDOG_STATUS_FILE', power_file):
            status = bot.read_power_status()
            assert status == "on"

    def test_read_power_status_file_not_exists(self, bot):
        """Test reading power status when file doesn't exist"""
        with patch('bot.WATCHDOG_STATUS_FILE', '/nonexistent/file.txt'):
            status = bot.read_power_status()
            assert status is None

    def test_read_last_status(self, bot, temp_files):
        """Test reading last status from file"""
        _, last_file = temp_files

        with open(last_file, 'w') as f:
            f.write("off")

        with patch('bot.BOT_LAST_NOTIFIED_STATUS_FILE', last_file):
            status = bot.read_last_status()
            assert status == "off"

    def test_write_last_status(self, bot, temp_files):
        """Test writing last status to file"""
        _, last_file = temp_files

        with patch('bot.BOT_LAST_NOTIFIED_STATUS_FILE', last_file):
            bot.write_last_status("on")

        with open(last_file, 'r') as f:
            content = f.read()
            assert content == "on"

    @pytest.mark.asyncio
    async def test_monitor_power_status_detects_change(self, bot, temp_files):
        """Test that monitoring detects power status changes"""
        power_file, last_file = temp_files

        # Setup initial status
        with open(power_file, 'w') as f:
            f.write("off\n")

        with patch('bot.WATCHDOG_STATUS_FILE', power_file), \
             patch('bot.BOT_LAST_NOTIFIED_STATUS_FILE', last_file):

            # Mock send_message
            bot.send_message = AsyncMock(return_value=True)

            # Start monitoring in background
            monitor_task = asyncio.create_task(bot.monitor_power_status(check_interval=0.1))

            # Wait a bit for initial status to be read
            await asyncio.sleep(0.15)

            # Change status
            with open(power_file, 'w') as f:
                f.write("on\n")

            # Wait for monitoring to detect change
            await asyncio.sleep(0.15)

            # Stop monitoring
            bot.stop_monitoring()
            await asyncio.sleep(0.05)

            # Cancel the task
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

            # Verify message was sent
            assert bot.send_message.called
            assert bot.last_status == "on"

    def test_stop_monitoring(self, bot):
        """Test stopping the monitoring loop"""
        bot.monitoring = True
        bot.stop_monitoring()
        assert bot.monitoring is False


class TestFileOperations:
    """Test file read/write operations"""

    def test_write_and_read_consistency(self):
        """Test that written status can be read back correctly"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            temp_file = f.name

        try:
            with patch('bot.TELEGRAM_BOT_TOKEN', 'test'), \
                 patch('bot.TELEGRAM_CHANNEL_ID', '@test'), \
                 patch('bot.Bot'):
                bot = TelegramChannelBot()

                with patch('bot.BOT_LAST_NOTIFIED_STATUS_FILE', temp_file):
                    bot.write_last_status("on")
                    status = bot.read_last_status()
                    assert status == "on"
        finally:
            try:
                os.unlink(temp_file)
            except:
                pass
