"""Telegram bot that bridges to Zylch ChatService.

Receives messages via Telegram long-polling, routes them
through the same ChatService used by the CLI REPL, and
sends responses back. Mono-user, secured by allowed_user_id.

Usage:
    zylch telegram          # Start bot (blocking)
    TELEGRAM_BOT_TOKEN=... zylch telegram
"""

import asyncio
import html
import logging
import re
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
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
    """Get owner_id for the active profile.

    Delegates to the canonical resolver in cli/utils — same value the
    RPC handlers, process_pipeline, and WhatsAppSyncService use. The
    previous implementation read ``settings.owner_id`` (= ``OWNER_ID``
    env var, fallback ``"owner_default"``), which doesn't match
    ``get_owner_id()`` = ``EMAIL_ADDRESS`` — so the bot was reading
    rows under a different key than the engine had written them under
    and reported zero tasks on every profile.
    """
    from zylch.cli.utils import get_owner_id

    return get_owner_id()


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


# Approval futures awaiting a button press, keyed by tool_use_id. The engine's
# tool loop blocks on the future while the human decides, so this never grows
# beyond the handful of approvals one conversation has in flight.
_pending_approvals: Dict[str, asyncio.Future] = {}

# How long the bot waits for a tap before treating silence as a refusal. The
# same budget the RPC gate uses, for the same reason: an approval nobody
# answered is not an approval.
APPROVAL_TIMEOUT_S = 600


def _make_approval_callback(update: Update):
    """Build the approval gate for one Telegram conversation.

    The bot reaches the same tools as the desktop app and the REPL, so it needs
    the same gate rather than an exemption from it — a bot that could send mail
    without asking would be the widest ungated surface of the three, since the
    human is not even at the machine.

    One difference from the desktop card, and it is a real limitation: Telegram
    inline buttons approve or refuse, they cannot EDIT the recipient or body.
    A draft that is wrong has to be redrafted, not corrected here.
    """

    async def approval_callback(tool_use_id: str, tool_name: str, tool_input: dict):
        from zylch.services.task_executor import format_approval_preview

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        _pending_approvals[tool_use_id] = fut

        preview = format_approval_preview(tool_name, tool_input)
        if len(preview) > 3000:
            preview = preview[:2997] + "..."
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve:{tool_use_id}"),
                    InlineKeyboardButton("❌ Refuse", callback_data=f"refuse:{tool_use_id}"),
                ]
            ]
        )
        try:
            await update.effective_chat.send_message(
                text=_md_to_telegram_html(f"**Approval required: {tool_name}**\n\n{preview}"),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        except Exception as e:
            # Could not even ask. That is a refusal, not a licence to proceed.
            logger.error(f"[telegram] could not post approval for {tool_name}: {e}")
            _pending_approvals.pop(tool_use_id, None)
            return (False, None)

        try:
            approved = await asyncio.wait_for(fut, timeout=APPROVAL_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning(f"[telegram] approval timed out for {tool_name}")
            approved = False
        finally:
            _pending_approvals.pop(tool_use_id, None)
        return (bool(approved), None)

    return approval_callback


async def handle_approval_press(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Resolve the future the tool loop is waiting on."""
    query = update.callback_query
    if not _check_authorized(update.effective_user.id):
        await query.answer("Not authorized.")
        return

    await query.answer()
    action, _, tool_use_id = (query.data or "").partition(":")
    approved = action == "approve"
    fut = _pending_approvals.get(tool_use_id)
    if fut is None or fut.done():
        await query.edit_message_text("This approval has already been answered or expired.")
        return
    fut.set_result(approved)
    await query.edit_message_text("✅ Approved." if approved else "❌ Refused.")


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
            approval_callback=_make_approval_callback(update),
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
            approval_callback=_make_approval_callback(update),
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

    # Button presses on an approval card. Registered before the catch-all
    # message handlers because the tool loop is blocked waiting on it.
    app.add_handler(CallbackQueryHandler(handle_approval_press))

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

    # Proactive digest scheduler (8am and 8pm)
    if allowed:
        _setup_digest_scheduler(app, str(allowed))

    print("Press Ctrl-C to stop.\n")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


def _setup_digest_scheduler(app: Application, user_id: str):
    """Set up APScheduler for proactive digest messages."""
    try:
        from apscheduler.schedulers.asyncio import (
            AsyncIOScheduler,
        )
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning(
            "[telegram] apscheduler not available," " digest disabled",
        )
        return

    from zylch.cli.utils import get_owner_id

    owner_id = get_owner_id()

    async def _send_digest():
        """Build and send digest if there's something to report."""
        try:
            from zylch.services.digest import build_digest
            from zylch.storage.storage import Storage

            store = Storage.get_instance()
            msg = build_digest(owner_id, store)
            if msg:
                await app.bot.send_message(
                    chat_id=int(user_id),
                    text=msg,
                    parse_mode=ParseMode.MARKDOWN,
                )
                logger.info("[telegram] Digest sent")
        except Exception as e:
            logger.error(f"[telegram] Digest failed: {e}")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _send_digest,
        CronTrigger(hour="8,20"),  # 8am and 8pm
        id="zylch_digest",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "[telegram] Digest scheduler started (8am, 8pm)",
    )
