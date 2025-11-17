#!/usr/bin/env python3
"""Telegram Channel Manager CLI - Command-line interface for managing Telegram channels."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from channel_manager import TelegramChannelManager


def load_config():
    """Load configuration from .env file."""
    # Look for .env in the script's directory
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()  # Try to load from current directory

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE")

    if not all([api_id, api_hash, phone]):
        print("Error: Missing required environment variables")
        print("Please create a .env file with:")
        print("  - TELEGRAM_API_ID")
        print("  - TELEGRAM_API_HASH")
        print("  - TELEGRAM_PHONE")
        print("\nGet API credentials from https://my.telegram.org/apps")
        sys.exit(1)

    try:
        api_id = int(api_id)
    except ValueError:
        print("Error: TELEGRAM_API_ID must be a number")
        sys.exit(1)

    state_file = os.getenv("STATE_FILE", "channels.json")
    session_name = os.getenv("SESSION_NAME", "telegram_session")

    return api_id, api_hash, phone, state_file, session_name


async def cmd_create(manager: TelegramChannelManager, args):
    """Create a new channel."""
    result = await manager.create_channel(
        args.title, args.description or "", args.megagroup
    )
    if result["success"]:
        print(f"✓ {result['message']}")
        print(f"\nChannel details:")
        channel = result["channel"]
        print(f"  ID: {channel['id']}")
        print(f"  Title: {channel['title']}")
        print(f"  Type: {channel['type']}")
        if channel.get("username"):
            print(f"  Username: @{channel['username']}")
        else:
            print(
                f"  Username: (not set - use 'set-username' command to add a public link)"
            )
        if channel.get("description"):
            print(f"  Description: {channel['description']}")
    else:
        print(f"✗ {result['message']}")
        sys.exit(1)


async def cmd_info(manager: TelegramChannelManager, args):
    """Get information about a channel."""
    info = await manager.get_channel_info(args.identifier)
    if info:
        print(f"Channel information:")
        print(f"  ID: {info['id']}")
        print(f"  Title: {info['title']}")
        print(
            f"  Username: @{info['username']}" if info["username"] else "  Username: (none)"
        )
        print(f"  Type: {info['type']}")
        if info.get("about"):
            print(f"  About: {info['about']}")
        if info.get("participants_count") is not None:
            print(f"  Members: {info['participants_count']}")
        if info.get("friendly_name"):
            print(f"  Friendly name: {info['friendly_name']}")
        if info.get("created_at"):
            print(f"  Created: {info['created_at']}")
        if info.get("managed") is False:
            print(f"  Note: This channel is not in your managed channels list")
    else:
        print(f"✗ Channel not found: {args.identifier}")
        sys.exit(1)


async def cmd_list(manager: TelegramChannelManager, args):
    """List all managed channels."""
    tags = args.tags.split(",") if args.tags else None
    channels = await manager.list_channels(tags=tags)
    if not channels:
        if tags:
            print(f"No managed channels found with tags: {', '.join(tags)}")
        else:
            print("No managed channels found.")
            print("Use 'create' command to create a new channel.")
        return

    if tags:
        print(f"Managed channels with tags {', '.join(tags)} ({len(channels)}):\n")
    else:
        print(f"Managed channels ({len(channels)}):\n")

    for i, channel in enumerate(channels, 1):
        print(f"{i}. {channel['title']}")
        print(f"   ID: {channel['id']}")
        if channel.get("username"):
            print(f"   Username: @{channel['username']}")
        if channel.get("friendly_name"):
            print(f"   Friendly name: {channel['friendly_name']}")
        print(f"   Type: {channel.get('type', 'channel')}")
        if channel.get("tags"):
            print(f"   Tags: {', '.join(channel['tags'])}")
        print(f"   Created: {channel.get('created_at', 'Unknown')}")
        print()


async def cmd_remove(manager: TelegramChannelManager, args):
    """Remove a channel from managed channels (doesn't delete the channel)."""
    result = await manager.remove_channel(args.identifier)
    if result["success"]:
        print(f"✓ {result['message']}")
    else:
        print(f"✗ {result['message']}")
        sys.exit(1)


async def cmd_rename(manager: TelegramChannelManager, args):
    """Update the friendly name of a channel."""
    result = await manager.update_channel_name(args.identifier, args.name)
    if result["success"]:
        print(f"✓ {result['message']}")
    else:
        print(f"✗ {result['message']}")
        sys.exit(1)


async def cmd_set_username(manager: TelegramChannelManager, args):
    """Set or update the username (public link) for a channel."""
    result = await manager.set_channel_username(args.identifier, args.username)
    if result["success"]:
        print(f"✓ {result['message']}")
    else:
        print(f"✗ {result['message']}")
        sys.exit(1)


async def cmd_delete(manager: TelegramChannelManager, args):
    """Delete a channel permanently."""
    if not args.confirm:
        print(
            "Warning: This will permanently delete the channel from Telegram!"
        )
        confirm = input(
            f"Are you sure you want to delete '{args.identifier}'? Type 'yes' to confirm: "
        )
        if confirm.lower() != "yes":
            print("Cancelled.")
            return

    result = await manager.delete_channel(args.identifier)
    if result["success"]:
        print(f"✓ {result['message']}")
    else:
        print(f"✗ {result['message']}")
        sys.exit(1)


async def cmd_add_tags(manager: TelegramChannelManager, args):
    """Add tags to a channel."""
    tags = args.tags.split(",")
    result = await manager.add_tags(args.identifier, tags)
    if result["success"]:
        print(f"✓ {result['message']}")
        print(f"   Current tags: {', '.join(result['tags'])}")
    else:
        print(f"✗ {result['message']}")
        sys.exit(1)


async def cmd_remove_tags(manager: TelegramChannelManager, args):
    """Remove tags from a channel."""
    tags = args.tags.split(",")
    result = await manager.remove_tags(args.identifier, tags)
    if result["success"]:
        print(f"✓ {result['message']}")
        print(f"   Current tags: {', '.join(result['tags'])}")
    else:
        print(f"✗ {result['message']}")
        sys.exit(1)


async def cmd_script(manager: TelegramChannelManager, args):
    """Run a script from the scripts directory."""
    import importlib.util
    from pathlib import Path

    script_path = Path(__file__).parent / "scripts" / f"{args.script_name}.py"

    if not script_path.exists():
        print(f"✗ Script not found: {script_path}")
        print(f"\nAvailable scripts:")
        scripts_dir = Path(__file__).parent / "scripts"
        if scripts_dir.exists():
            for script in scripts_dir.glob("*.py"):
                if script.name != "__init__.py":
                    print(f"  - {script.stem}")
        sys.exit(1)

    # Load the script module
    spec = importlib.util.spec_from_file_location(args.script_name, script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Run the script's main function
    if hasattr(module, "run"):
        await module.run(manager, args.script_args)
    else:
        print(f"✗ Script {args.script_name} does not have a 'run' function")
        sys.exit(1)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Telegram Channel Manager - Create and manage your Telegram channels",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s create "My Channel" --description "A channel for updates"
  %(prog)s create "My Group" --megagroup
  %(prog)s set-username "My Channel" mychannel
  %(prog)s info @mychannel
  %(prog)s list
  %(prog)s rename @mychannel "Production Channel"
  %(prog)s delete @mychannel
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    subparsers.required = True

    # Create command
    parser_create = subparsers.add_parser("create", help="Create a new channel")
    parser_create.add_argument("title", help="Channel title")
    parser_create.add_argument(
        "--description", "-d", help="Channel description", default=""
    )
    parser_create.add_argument(
        "--megagroup",
        "-m",
        action="store_true",
        help="Create as supergroup instead of broadcast channel",
    )
    parser_create.set_defaults(func=cmd_create)

    # Info command
    parser_info = subparsers.add_parser("info", help="Get channel information")
    parser_info.add_argument("identifier", help="Channel ID, @username, or friendly name")
    parser_info.set_defaults(func=cmd_info)

    # List command
    parser_list = subparsers.add_parser("list", help="List all managed channels")
    parser_list.add_argument("--tags", "-t", help="Filter by tags (comma-separated)")
    parser_list.set_defaults(func=cmd_list)

    # Remove command
    parser_remove = subparsers.add_parser(
        "remove", help="Remove a channel from managed list (doesn't delete it)"
    )
    parser_remove.add_argument("identifier", help="Channel ID, @username, or friendly name")
    parser_remove.set_defaults(func=cmd_remove)

    # Rename command
    parser_rename = subparsers.add_parser("rename", help="Update channel friendly name")
    parser_rename.add_argument("identifier", help="Channel ID, @username, or friendly name")
    parser_rename.add_argument("name", help="New friendly name")
    parser_rename.set_defaults(func=cmd_rename)

    # Set username command
    parser_username = subparsers.add_parser(
        "set-username", help="Set or update channel username (public link)"
    )
    parser_username.add_argument("identifier", help="Channel ID or friendly name")
    parser_username.add_argument("username", help="New username (without @)")
    parser_username.set_defaults(func=cmd_set_username)

    # Delete command
    parser_delete = subparsers.add_parser(
        "delete", help="Delete a channel permanently from Telegram"
    )
    parser_delete.add_argument("identifier", help="Channel ID, @username, or friendly name")
    parser_delete.add_argument(
        "--confirm", "-y", action="store_true", help="Skip confirmation prompt"
    )
    parser_delete.set_defaults(func=cmd_delete)

    # Add tags command
    parser_add_tags = subparsers.add_parser("add-tags", help="Add tags to a channel")
    parser_add_tags.add_argument("identifier", help="Channel ID, @username, or friendly name")
    parser_add_tags.add_argument("tags", help="Tags to add (comma-separated)")
    parser_add_tags.set_defaults(func=cmd_add_tags)

    # Remove tags command
    parser_remove_tags = subparsers.add_parser("remove-tags", help="Remove tags from a channel")
    parser_remove_tags.add_argument("identifier", help="Channel ID, @username, or friendly name")
    parser_remove_tags.add_argument("tags", help="Tags to remove (comma-separated)")
    parser_remove_tags.set_defaults(func=cmd_remove_tags)

    # Script command
    parser_script = subparsers.add_parser("script", help="Run a script from scripts directory")
    parser_script.add_argument("script_name", help="Name of the script (without .py)")
    parser_script.add_argument("script_args", nargs="*", help="Arguments to pass to the script")
    parser_script.set_defaults(func=cmd_script)

    args = parser.parse_args()

    # Load configuration
    api_id, api_hash, phone, state_file, session_name = load_config()

    # Create manager
    manager = TelegramChannelManager(api_id, api_hash, phone, state_file, session_name)

    # Execute command
    async def run():
        try:
            await manager.connect()
            await args.func(manager, args)
        finally:
            await manager.disconnect()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
