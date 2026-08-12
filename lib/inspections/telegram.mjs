// Thin Telegram Bot API wrapper.

const API = 'https://api.telegram.org';
export const MAX_LEN = 4096;

export const escapeHtml = (s) =>
  String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

function token() {
  const t = process.env.TELEGRAM_BOT_TOKEN;
  if (!t) throw new Error('TELEGRAM_BOT_TOKEN is not set');
  return t;
}

export async function call(method, payload) {
  const res = await fetch(`${API}/bot${token()}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body.ok === false) {
    throw new Error(`Telegram ${method} failed (${res.status}): ${body.description || 'unknown error'}`);
  }
  return body.result;
}

export function sendMessage(chatId, text, { keyboard, replyTo } = {}) {
  return call('sendMessage', {
    chat_id: chatId,
    text,
    parse_mode: 'HTML',
    link_preview_options: { is_disabled: true },
    ...(keyboard ? { reply_markup: { inline_keyboard: keyboard } } : {}),
    ...(replyTo ? { reply_parameters: { message_id: replyTo } } : {}),
  });
}

export function answerCallback(callbackQueryId, text = '') {
  return call('answerCallbackQuery', { callback_query_id: callbackQueryId, text });
}

/**
 * Split text so no piece exceeds Telegram's limit, breaking on blank lines and
 * then on line boundaries — never mid-line, which would tear an HTML tag apart.
 */
export function splitMessage(text, limit = MAX_LEN) {
  if (text.length <= limit) return [text];
  const chunks = [];
  let current = '';

  const push = () => {
    if (current) chunks.push(current);
    current = '';
  };

  for (const block of text.split('\n\n')) {
    const candidate = current ? `${current}\n\n${block}` : block;
    if (candidate.length <= limit) {
      current = candidate;
      continue;
    }
    push();
    if (block.length <= limit) {
      current = block;
      continue;
    }
    for (const line of block.split('\n')) {
      const lineCandidate = current ? `${current}\n${line}` : line;
      if (lineCandidate.length <= limit) current = lineCandidate;
      else {
        push();
        current = line.slice(0, limit);
      }
    }
  }
  push();
  return chunks;
}
