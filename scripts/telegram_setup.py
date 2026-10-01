#!/usr/bin/env python3
"""Interactive wizard that fills BOT_TOKEN, GROUP_ID and ADMIN_IDS in .env.

Run from the repo root while the bot container is stopped:
    python3 scripts/telegram_setup.py

Uses only the standard library. Exits 0 when all three values are set, 1 otherwise.
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_PATH = Path(".env")
API_URL = "https://api.telegram.org/bot{token}/{method}"
TOKEN_RE = re.compile(r"^\d+:[\w-]+$")
POLL_TIMEOUT = 25

GREEN, YELLOW, RED, NC = "\033[0;32m", "\033[1;33m", "\033[0;31m", "\033[0m"


def info(text):
    print(f"{GREEN}[+]{NC} {text}")


def warn(text):
    print(f"{YELLOW}[!]{NC} {text}")


def error(text):
    print(f"{RED}[x]{NC} {text}")


# ── Telegram API ──────────────────────────────────────────────────────────────

class TelegramError(Exception):
    def __init__(self, code, description, parameters=None):
        super().__init__(description)
        self.code = code
        self.parameters = parameters or {}


def api(token, method, **params):
    url = API_URL.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(url, data, timeout=POLL_TIMEOUT + 15) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except ValueError:
            raise TelegramError(e.code, str(e.reason))
    if not body.get("ok"):
        raise TelegramError(
            body.get("error_code"), body.get("description", "unknown error"), body.get("parameters")
        )
    return body["result"]


def wait_for(token, accept):
    """Long-polls updates until accept(update) returns something truthy."""
    offset = None
    while True:
        params = {
            "timeout": POLL_TIMEOUT,
            "allowed_updates": json.dumps(["message", "my_chat_member"]),
        }
        if offset is not None:
            params["offset"] = offset
        for update in api(token, "getUpdates", **params):
            offset = update["update_id"] + 1
            result = accept(update)
            if result:
                # Confirm what we consumed so the bot does not replay it on first start
                api(token, "getUpdates", offset=offset, timeout=0, limit=1)
                return result


# ── .env helpers ──────────────────────────────────────────────────────────────

def read_env():
    values = {}
    for line in ENV_PATH.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def write_env(key, value):
    lines = ENV_PATH.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n")


# ── Wizard steps ──────────────────────────────────────────────────────────────

def ask_token(token):
    """Returns (token, getMe result), or (None, None) if the user skipped."""
    while True:
        if not token:
            token = input("Bot token (Enter to skip): ").strip()
            if not token:
                return None, None
        if TOKEN_RE.match(token):
            try:
                return token, api(token, "getMe")
            except TelegramError as e:
                warn(f"Telegram rejected the token: {e}")
        else:
            warn("That does not look like a bot token (expected 123456789:ABC...).")
        token = ""


def describe_user(user):
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
    username = f"@{user['username']}, " if user.get("username") else ""
    return f"{name} ({username}id {user['id']})"


def confirm(question):
    return input(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes", "д", "да")


def update_chat_and_user(update):
    """Returns (chat, user) for updates that show where the bot is and who acted, else None."""
    member = update.get("my_chat_member")
    if member:
        if member["new_chat_member"]["status"] not in ("member", "administrator"):
            return None
        chat, user = member["chat"], member["from"]
    else:
        message = update.get("message")
        if not message or "from" not in message:
            return None
        chat, user = message["chat"], message["from"]
    if user.get("is_bot"):  # anonymous group admins post as a bot account
        return None
    return chat, user


def make_picker(chat_types, question):
    """Builds a wait_for() callback that asks the user to confirm each new candidate."""
    rejected = set()

    def pick(update):
        found = update_chat_and_user(update)
        if not found:
            return None
        chat, user = found
        key = (chat["id"], user["id"])
        if chat["type"] not in chat_types or key in rejected:
            return None
        if confirm(question(chat, user)):
            return chat, user
        rejected.add(key)
        print("Waiting for another one...")
        return None

    return pick


def wait_until_admin(token, group_id, me):
    """Blocks until the bot is an administrator of the group. Returns the (possibly migrated) group id."""
    while True:
        try:
            status = api(token, "getChatMember", chat_id=group_id, user_id=me["id"])["status"]
        except TelegramError as e:
            migrated = e.parameters.get("migrate_to_chat_id")
            if migrated:  # promoting a bot can upgrade a basic group to a supergroup with a new id
                group_id = str(migrated)
                write_env("GROUP_ID", group_id)
                continue
            status = f"error: {e}"
        if status == "administrator":
            info("Bot is an administrator of the group.")
            return group_id
        warn(f"@{me['username']} is not an administrator of the group yet ({status}).")
        answer = input("Promote it, then press Enter (or type 'skip'): ")
        if answer.strip().lower() == "skip":
            warn("Skipped. Membership checks and the pinned status message need admin rights.")
            return group_id


def run():
    if not ENV_PATH.exists():
        error(".env not found. Run scripts/setup.sh from the repo root first.")
        return 1

    env = read_env()
    token = env.get("BOT_TOKEN", "")
    group_id = env.get("GROUP_ID", "")
    admin_ids = env.get("ADMIN_IDS", "")

    if token and group_id and admin_ids:
        info("Telegram settings already present in .env.")
        return 0
    if not sys.stdin.isatty():
        warn("No terminal attached. Set BOT_TOKEN, GROUP_ID and ADMIN_IDS in .env manually.")
        return 1

    print("\n=== Telegram setup ===\n")
    if not token:
        print("Create a bot: open https://t.me/BotFather, send /newbot and follow the steps.")
        print("Then paste the token it gives you.\n")
    token, me = ask_token(token)
    if token is None:
        return 1
    write_env("BOT_TOKEN", token)
    username = me["username"]
    info(f"Bot: @{username}")

    if not group_id:
        if not me.get("can_join_groups", True):
            warn("This bot cannot join groups. Enable it in @BotFather: /setjoingroups.")
        print(
            f"\nNow connect the bot to the group whose members may use the VPN:\n"
            f"  1. Add @{username} to the group.\n"
            f"  2. Promote it to administrator.\n"
            f"If the bot is already in the group, send /start@{username} there instead.\n"
            f"\nWaiting for the bot to show up in a group... (Ctrl+C to skip)"
        )

        def question(chat, user):
            text = f"Group: «{chat.get('title', '?')}» (id {chat['id']})"
            if not admin_ids:
                text += f"\nBot admin: {describe_user(user)}"
            return text + "\nUse this?"

        chat, user = wait_for(token, make_picker(("group", "supergroup"), question))
        group_id = str(chat["id"])
        write_env("GROUP_ID", group_id)
        if not admin_ids:
            admin_ids = str(user["id"])
            write_env("ADMIN_IDS", admin_ids)
        group_id = wait_until_admin(token, group_id, me)

    if not admin_ids:
        print(
            f"\nSend /start to @{username} in a private chat from the account that should be the bot admin.\n"
            f"Waiting... (Ctrl+C to skip)"
        )
        _, user = wait_for(
            token,
            make_picker(("private",), lambda chat, user: f"Bot admin: {describe_user(user)}\nUse this?"),
        )
        admin_ids = str(user["id"])
        write_env("ADMIN_IDS", admin_ids)

    info(f"Saved to .env: GROUP_ID={group_id}, ADMIN_IDS={admin_ids}")
    return 0


def main():
    try:
        return run()
    except (KeyboardInterrupt, EOFError):
        print()
        warn("Telegram setup interrupted. Re-run it with: python3 scripts/telegram_setup.py")
    except TelegramError as e:
        if e.code == 409:
            error("Something else is receiving this bot's updates (running bot container or a webhook).")
            error("Stop it first: docker compose stop bot")
        else:
            error(f"Telegram API error: {e}")
    except OSError as e:
        error(f"Cannot reach api.telegram.org: {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
