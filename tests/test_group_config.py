"""Tests for GroupConfig model with dynamic group support"""
import pytest
from unittest.mock import Mock, patch
from light_bot.models.group_config import GroupConfig


class TestGroupConfigStaticGroup:
    """Test GroupConfig with static group configuration"""

    def test_static_group_creation(self):
        """Test creating a GroupConfig with static group"""
        config = GroupConfig(
            id="home",
            group="2.1",
            city="kiev"
        )
        assert config.id == "home"
        assert config.group == "2.1"
        assert config.city == "kiev"
        assert config.group_dynamic is None

    def test_static_group_resolve(self):
        """Test resolve_group returns static group without fetching"""
        config = GroupConfig(
            id="home",
            group="2.1",
            city="kiev"
        )
        result, changed = config.resolve_group()
        assert result == "2.1"
        assert changed == False
        assert config.group == "2.1"

    def test_missing_id_raises_error(self):
        """Test that missing id raises ValueError"""
        with pytest.raises(ValueError, match="id cannot be empty"):
            GroupConfig(
                id="",
                group="2.1",
                city="kiev"
            )

    def test_missing_city_raises_error(self):
        """Test that missing city raises ValueError"""
        with pytest.raises(ValueError, match="city cannot be empty"):
            GroupConfig(
                id="home",
                group="2.1",
                city=""
            )

    def test_invalid_id_characters(self):
        """Test that invalid characters in id raise ValueError"""
        with pytest.raises(ValueError, match="id must contain only alphanumeric"):
            GroupConfig(
                id="home@test",
                group="2.1",
                city="kiev"
            )


class TestGroupConfigDynamicGroup:
    """Test GroupConfig with dynamic group configuration"""

    @patch('light_bot.models.group_config.requests.get')
    def test_dynamic_group_resolve_success(self, mock_get):
        """Test successful dynamic group resolution"""
        # Mock successful API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"group": 5, "subgroup": 1}
        mock_get.return_value = mock_response

        config = GroupConfig(
            id="home",
            group_dynamic="https://app.yasno.ua/api/test",
            city="kiev"
        )
        
        result, changed = config.resolve_group()
        
        assert result == "5.1"
        assert changed == True
        assert config.group == "5.1"
        mock_get.assert_called_once_with("https://app.yasno.ua/api/test", timeout=10)

    @patch('light_bot.models.group_config.requests.get')
    def test_dynamic_group_different_values(self, mock_get):
        """Test dynamic group with different group/subgroup values"""
        mock_response = Mock()
        mock_response.json.return_value = {"group": 3, "subgroup": 2}
        mock_get.return_value = mock_response

        config = GroupConfig(
            id="office",
            group_dynamic="https://app.yasno.ua/api/test",
            city="kiev"
        )
        
        result, changed = config.resolve_group()
        
        assert result == "3.2"
        assert changed == True
        assert config.group == "3.2"

    @patch('light_bot.models.group_config.requests.get')
    def test_dynamic_group_http_error(self, mock_get):
        """Test dynamic group resolution with HTTP error"""
        import requests
        mock_get.side_effect = requests.exceptions.RequestException("Connection error")

        config = GroupConfig(
            id="home",
            group_dynamic="https://app.yasno.ua/api/test",
            city="kiev"
        )
        
        with pytest.raises(ValueError, match="Failed to fetch dynamic group"):
            config.resolve_group()

    @patch('light_bot.models.group_config.requests.get')
    def test_dynamic_group_invalid_response_format(self, mock_get):
        """Test dynamic group resolution with invalid JSON format"""
        mock_response = Mock()
        mock_response.json.return_value = {"invalid": "format"}
        mock_get.return_value = mock_response

        config = GroupConfig(
            id="home",
            group_dynamic="https://app.yasno.ua/api/test",
            city="kiev"
        )
        
        with pytest.raises(ValueError, match="Response missing 'group' or 'subgroup' fields"):
            config.resolve_group()

    @patch('light_bot.models.group_config.requests.get')
    def test_dynamic_group_non_dict_response(self, mock_get):
        """Test dynamic group resolution with non-dict response"""
        mock_response = Mock()
        mock_response.json.return_value = ["not", "a", "dict"]
        mock_get.return_value = mock_response

        config = GroupConfig(
            id="home",
            group_dynamic="https://app.yasno.ua/api/test",
            city="kiev"
        )
        
        with pytest.raises(ValueError, match="Expected JSON object"):
            config.resolve_group()


class TestGroupConfigValidation:
    """Test GroupConfig validation rules"""

    def test_both_group_and_dynamic_raises_error(self):
        """Test that specifying both group and group_dynamic raises error"""
        with pytest.raises(ValueError, match="Cannot specify both 'group' and 'group_dynamic'"):
            GroupConfig(
                id="home",
                group="2.1",
                group_dynamic="https://app.yasno.ua/api/test",
                city="kiev"
            )

    def test_neither_group_nor_dynamic_raises_error(self):
        """Test that missing both group and group_dynamic raises error"""
        with pytest.raises(ValueError, match="Must specify either 'group' or 'group_dynamic'"):
            GroupConfig(
                id="home",
                city="kiev"
            )


class TestGroupConfigProperties:
    """Test GroupConfig properties and methods"""

    def test_file_suffix_property(self):
        """Test file_suffix property"""
        config = GroupConfig(
            id="kyiv_home",
            group="2.1",
            city="kiev"
        )
        assert config.file_suffix == "kyiv_home"

    def test_target_channel_with_chat_id(self):
        """Test target_channel returns chat_id when set"""
        config = GroupConfig(
            id="home",
            group="2.1",
            city="kiev",
            chat_id=-123456
        )
        assert config.target_channel == -123456

    def test_target_channel_with_channel(self):
        """Test target_channel returns channel when chat_id not set"""
        config = GroupConfig(
            id="home",
            group="2.1",
            city="kiev",
            channel="@test_channel"
        )
        assert config.target_channel == "@test_channel"

    def test_target_channel_none(self):
        """Test target_channel returns None when neither is set"""
        config = GroupConfig(
            id="home",
            group="2.1",
            city="kiev"
        )
        assert config.target_channel is None

    def test_str_representation(self):
        """Test string representation"""
        config = GroupConfig(
            id="home",
            group="2.1",
            city="kiev",
            channel="@test"
        )
        str_repr = str(config)
        assert "home" in str_repr
        assert "2.1" in str_repr
        assert "kiev" in str_repr
        assert "@test" in str_repr
