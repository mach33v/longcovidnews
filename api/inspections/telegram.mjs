// Telegram webhook: handles taps on the digest's numbered buttons by fetching
// that inspection's violations and replying with them.
//
// Register it once with:
//   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
//     -d url="https://<your-domain>/api/inspections/telegram" \
//     -d secret_token="<TELEGRAM_WEBHOOK_SECRET>" \
//     -d allowed_updates='["callback_query"]'

import { byKey, fetchViolations, PortalBlocked } from '../../lib/inspections/portal.mjs';
import { buildViolationsMessage } from '../../lib/inspections/format.mjs';
import { answerCallback, sendMessage, splitMessage } from '../../lib/inspections/telegram.mjs';

export const config = { maxDuration: 30 };

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end();

  const secret = process.env.TELEGRAM_WEBHOOK_SECRET;
  if (secret && req.headers['x-telegram-bot-api-secret-token'] !== secret) {
    return res.status(401).json({ error: 'bad secret token' });
  }

  const update = req.body || {};
  const query = update.callback_query;
  // Telegram retries anything that isn't a 200, so unknown updates ack quietly.
  if (!query) return res.status(200).json({ ok: true, ignored: true });

  const chatId = query.message?.chat?.id;
  const allowedChat = process.env.TELEGRAM_CHAT_ID;
  if (allowedChat && String(chatId) !== String(allowedChat)) {
    await answerCallback(query.id, 'Not available in this chat.').catch(() => {});
    return res.status(200).json({ ok: true, ignored: 'chat not allowed' });
  }

  const [action, jurisdictionKey, inspectionId] = String(query.data || '').split('|');
  if (action !== 'v' || !jurisdictionKey || !inspectionId) {
    await answerCallback(query.id).catch(() => {});
    return res.status(200).json({ ok: true, ignored: 'unrecognized callback' });
  }

  const jurisdiction = byKey(jurisdictionKey);
  if (!jurisdiction) {
    await answerCallback(query.id, 'Unknown jurisdiction.').catch(() => {});
    return res.status(200).json({ ok: true, ignored: 'unknown jurisdiction' });
  }

  // Acknowledge within Telegram's timeout, then do the slow work.
  await answerCallback(query.id, 'Fetching violations…').catch(() => {});

  const url = `https://inspections.myhealthdepartment.com/${jurisdiction.path}/inspection/?inspectionID=${inspectionId}`;

  try {
    const detail = await fetchViolations(jurisdiction, inspectionId);
    const text = buildViolationsMessage({
      establishment: detail.establishment,
      date: detail.date,
      jurisdictionName: jurisdiction.name,
      url,
      violations: detail.violations,
    });
    for (const part of splitMessage(text)) {
      await sendMessage(chatId, part, { replyTo: query.message?.message_id });
    }
    return res.status(200).json({ ok: true, violations: detail.violations.length });
  } catch (e) {
    console.error('violation lookup failed:', e);
    const reason = e instanceof PortalBlocked
      ? 'the portal refused the request from this server'
      : 'the report could not be read';
    await sendMessage(
      chatId,
      `⚠️ Couldn't load the violations — ${reason}.\n<a href="${url}">Open the report</a>`,
      { replyTo: query.message?.message_id }
    ).catch(() => {});
    return res.status(200).json({ ok: false, error: e.message });
  }
}
