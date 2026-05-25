export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end();

  const { name, email, message } = req.body;
  if (!name || !email || !message) return res.status(400).json({ error: 'Missing fields' });

  const text = [
    `📬 <b>longcovidnews.com contact</b>`,
    ``,
    `<b>From:</b> ${name}`,
    `<b>Email:</b> ${email}`,
    `<b>Message:</b> ${message}`,
  ].join('\n');

  const r = await fetch(
    `https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}/sendMessage`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: process.env.TELEGRAM_CHAT_ID,
        text,
        parse_mode: 'HTML',
      }),
    }
  );

  if (!r.ok) {
    console.error('Telegram error:', await r.text());
    return res.status(500).json({ error: 'Failed to send' });
  }

  res.status(200).json({ ok: true });
}
