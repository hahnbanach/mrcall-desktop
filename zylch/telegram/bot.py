"""Telegram bot that bridges to Zylch ChatService.

Receives messages via Telegram long-polling, routes them
through the same ChatService used by the CLI REPL, and
sends responses back. Mono-user, secured by allowed_user_id.

Usage:
    zylch telegram          # Start bot (blocking)
    TELEGRAM_BOT_TOKEN=... zylch telegram
"""

import html
import logging
import re
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from zylch.config import settings

logger = logging.getLogger(__name__)

# Per-user conversation history (mono-user, so just one)
_conversation_history: list = []

# Lazy ChatService singleton
_chat_service = None

# Max Telegram message length
MAX_MSG_LEN = 4096

# Max conversation history entries (prevents unbounded growth)
MAX_HISTORY = 100


def _get_chat_service():
    """Get or create ChatService singleton."""
    global _chat_service
    if _chat_service is None:
        from zylch.services.chat_service import ChatService

        _chat_service = ChatService()
    return _chat_service


def _get_owner_id() -> str:
    """Get owner_id from settings."""
    return settings.owner_id or "owner_default"


def _check_authorized(user_id: int) -> bool:
    """Check if Telegram user is authorized.

    Default-deny: if TELEGRAM_ALLOWED_USER_ID is not set, reject all requests.
    """
    allowed = settings.telegram_allowed_user_id
    if not allowed:
        logger.warning(
            f"[telegram] TELEGRAM_ALLOWED_USER_ID not set — "
            f"request from user {user_id} denied (default-deny)"
        )
        return False
    return str(user_id) == str(allowed)


def _md_to_telegram_html(text: str) -> str:
    """Convert basic markdown from ChatService to Telegram HTML.

    Handles: **bold**, *italic*, `code`, ```blocks```,
    and escapes HTML entities. Protects code block content
    from bold/italic conversion.
    """
    # Extract code blocks first, replace with placeholders
    code_blocks = []

    def _save_fenced_block(m):
        code_blocks.append(m.group(0))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    # Fenced code blocks: ```...```
    text = re.sub(r"```\w*\n.*?```", _save_fenced_block, text, flags=re.DOTALL)
    text = re.sub(r"```.*?```", _save_fenced_block, text, flags=re.DOTALL)

    # Inline code: `...`
    def _save_inline_code(m):
        code_blocks.append(m.group(0))
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = re.sub(r"`[^`]+`", _save_inline_code, text)

    # Escape HTML entities in non-code text
    text = html.escape(text)

    # Bold: **...** → <b>...</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # Italic: *...* → <i>...</i> (but not inside bold)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)

    # Strikethrough: ~~...~~ → <s>...</s>
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Restore code blocks — escape HTML inside them separately
    for i, block in enumerate(code_blocks):
        if block.startswith("```"):
            # Fenced block
            inner = re.sub(r"^```\w*\n?", "", block)
            inner = re.sub(r"```$", "", inner)
            replacement = f"<pre>{html.escape(inner)}</pre>"
        else:
            # Inline code
            inner = block.strip("`")
            replacement = f"<code>{html.escape(inner)}</code>"
        text = text.replace(f"\x00CODEBLOCK{i}\x00", replacement)

    return text


async def _send_response(
    update: Update,
    text: str,
    parse_html: bool = True,
):
    """Send a response, splitting if longer than 4096 chars."""
    if not text:
        return

    if parse_html:
        text = _md_to_telegram_html(text)
        mode = ParseMode.HTML
    else:
        mode = None

    # Split long messages
    chunks = []
    while text:
        if len(text) <= MAX_MSG_LEN:
            chunks.append(text)
            break
        # Find a good split point (newline near the limit)
        split_at = text.rfind("\n", 0, MAX_MSG_LEN)
        if split_at < MAX_MSG_LEN // 2:
            split_at = MAX_MSG_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=mode)
        except Exception:
            # Fallback: send without formatting, unescape HTML entities
            plain = re.sub(r"<[^>]+>", "", chunk)
            plain = html.unescape(plain)
            await update.message.reply_text(plain)


def _trim_history():
    """Keep conversation history bounded."""
    if len(_conversation_history) > MAX_HISTORY:
        _conversation_history[:] = _conversation_history[-MAX_HISTORY:]


async def handle_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /start command — welcome message."""
    user = update.effective_user
    if not _check_authorized(user.id):
        await update.message.reply_text("Not authorized.")
        return

    logger.info(f"[telegram] /start from user {user.id} ({user.first_name})")
    await _send_response(
        update,
        (
            f"**Zylch AI** — sales intelligence assistant\n\n"
            f"Ciao {user.first_name}! Scrivi qualsiasi cosa come "
            f"nel REPL, oppure usa i comandi /help, /sync, /tasks, ecc.\n\n"
            f"Your Telegram ID: `{user.id}`"
        ),
    )


async def handle_clear(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle /clear — reset conversation history."""
    if not _check_authorized(update.effective_user.id):
        return
    _conversation_history.clear()
    await update.message.reply_text("Conversation cleared.")


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle any text message — route to ChatService."""
    user = update.effective_user
    if not _check_authorized(user.id):
        await update.message.reply_text("Not authorized.")
        return

    text = update.message.text
    if not text:
        return

    logger.debug(f"[telegram] message from {user.id}: {text[:80]}")

    owner_id = _get_owner_id()

    # Show "typing..." while processing
    await update.message.chat.send_action("typing")

    try:
        service = _get_chat_service()
        result = await service.process_message(
            user_message=text,
            user_id=owner_id,
            conversation_history=_conversation_history,
            context={"user_id": owner_id},
        )

        response = result.get("response", "")
        if response:
            await _send_response(update, response)

            # Update history (bounded) — only if response is non-empty
            _conversation_history.append({"role": "user", "content": text})
            _conversation_history.append({"role": "assistant", "content": response})
            _trim_history()

    except Exception as e:
        logger.error(f"[telegram] ChatService error: {e}", exc_info=True)
        await update.message.reply_text("An error occurred. Check server logs.")


async def handle_slash_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle slash commands forwarded to Zylch command handlers.

    Telegram sends /sync, /tasks etc. as bot commands.
    We route them to the same handlers as the CLI REPL.
    """
    user = update.effective_user
    if not _check_authorized(user.id):
        await update.message.reply_text("Not authorized.")
        return

    text = update.message.text
    if not text:
        return

    # Strip the @botname suffix Telegram may add (e.g. /sync@zylch_bot)
    text = re.sub(r"@\S+", "", text, count=1).strip()

    logger.debug(f"[telegram] command from {user.id}: {text}")

    owner_id = _get_owner_id()

    await update.message.chat.send_action("typing")

    try:
        # Route through ChatService which handles slash dispatch
        service = _get_chat_service()
        result = await service.process_message(
            user_message=text,
            user_id=owner_id,
            conversation_history=_conversation_history,
            context={"user_id": owner_id},
        )

        response = result.get("response", "")
        if response:
            await _send_response(update, response)

    except Exception as e:
        logger.error(f"[telegram] command error: {e}", exc_info=True)
        await update.message.reply_text("Command failed. Check server logs.")


def run_telegram_bot(token: Optional[str] = None):
    """Start the Telegram bot (blocking, long-polling).

    Args:
        token: Bot API token. If None, reads from settings.
    """
    bot_token = token or settings.telegram_bot_token
    if not bot_token:
        print(
            "Telegram bot token not configured.\n\n"
            "1. Message @BotFather on Telegram\n"
            "2. Send /newbot and follow instructions\n"
            "3. Add to ~/.zylch/.env:\n"
            "   TELEGRAM_BOT_TOKEN=your_token_here\n"
            "   TELEGRAM_ALLOWED_USER_ID=your_id  (recommended)\n\n"
            "Get your user ID: message @userinfobot on Telegram."
        )
        return

    logger.info("[telegram] Starting bot with long-polling")

    # Suppress noisy httpx logs from python-telegram-bot
    logging.getLogger("httpx").setLevel(logging.WARNING)

    app = Application.builder().token(bot_token).build()

    # /start and /clear handled explicitly
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("clear", handle_clear))

    # All other /commands → route to Zylch command handlers
    app.add_handler(MessageHandler(filters.COMMAND, handle_slash_command))

    # Free text → ChatService
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    allowed = settings.telegram_allowed_user_id
    if allowed:
        print(f"Telegram bot started (restricted to user {allowed})")
    else:
        print(
            "WARNING: Telegram bot started WITHOUT user restriction.\n"
            "Anyone who finds your bot can access your data.\n"
            "Set TELEGRAM_ALLOWED_USER_ID in ~/.zylch/.env for security."
        )
    print("Press Ctrl-C to stop.\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)
