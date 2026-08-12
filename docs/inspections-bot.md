# Richmond-area restaurant inspection digest

A weekly Telegram digest of restaurant inspections published by the Virginia
Department of Health for **Henrico County** and **Richmond City**. It runs on
Vercel Cron, sends one summary message, and fetches the violations for any
inspection on demand when you tap its number.

```
Vercel Cron ──► /api/inspections/digest ──► VDH portal ──► Telegram
                                                              │
     you tap a number ──► /api/inspections/telegram ◄──────────┘
                             └──► fetches that inspection's violations
```

## Files

| Path | Role |
| --- | --- |
| `api/inspections/digest.mjs` | Cron target. Fetches the week, sends the digest. |
| `api/inspections/telegram.mjs` | Webhook. Handles button taps, replies with violations. |
| `lib/inspections/portal.mjs` | VDH portal client (search + violations). |
| `lib/inspections/format.mjs` | Message and keyboard rendering. |
| `lib/inspections/telegram.mjs` | Telegram Bot API wrapper. |
| `scripts/check-digest.mjs` | Offline checks for the renderer. `node scripts/check-digest.mjs` |

## One-time setup

### 1. Create the bot and find your chat id

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Send your new bot any message.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and read
   `result[0].message.chat.id`. That's your chat id.

### 2. Set the environment variables in Vercel

Project → Settings → Environment Variables (Production):

| Variable | Required | What it does |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | yes | Bot token from BotFather. |
| `TELEGRAM_CHAT_ID` | yes | Where the digest goes; also the only chat the buttons work in. |
| `TELEGRAM_WEBHOOK_SECRET` | recommended | Any random string. Rejects webhook calls that aren't Telegram. |
| `CRON_SECRET` | recommended | Any random string. Vercel Cron sends it automatically; blocks strangers from triggering a send. |
| `DIGEST_WEEKDAY` | no | Day to send, `0`=Sunday … default `1` (Monday). |
| `INSPECTIONS_PROXY_TEMPLATE` | only if blocked | See [If the portal blocks Vercel](#if-the-portal-blocks-vercel). |

### 3. Deploy, then register the webhook

After the first production deploy:

```sh
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d url="https://longcovidnews.com/api/inspections/telegram" \
  -d secret_token="<TELEGRAM_WEBHOOK_SECRET>" \
  -d allowed_updates='["callback_query"]'
```

### 4. Confirm it can actually read the portal

```sh
curl -H "Authorization: Bearer $CRON_SECRET" \
  "https://longcovidnews.com/api/inspections/digest?diagnose=1"
```

`checks[0].ok: true` with a non-empty `sample` means everything works. If you
see `blocked: true`, read the next section.

Then preview the real message without sending it:

```sh
curl -H "Authorization: Bearer $CRON_SECRET" \
  "https://longcovidnews.com/api/inspections/digest?dry=1"
```

and send one on demand with `?force=1`.

## Schedule

`vercel.json` runs the cron **daily at 13:00 UTC** (9am ET in summer, 8am in
winter) and the handler exits immediately unless the day matches
`DIGEST_WEEKDAY`. That indirection exists because Vercel's Hobby plan only
guarantees daily cron granularity — change `DIGEST_WEEKDAY` to move the digest,
not the cron expression.

## If the portal blocks Vercel

`inspections.myhealthdepartment.com` sits behind an AWS WAF that answers `403`
to a lot of datacenter traffic. Verified during development: GitHub Actions
runners, a third-party reader service, and real headless Chromium were all
refused, from every path, with browser-identical headers. Ordinary home
connections are served normally. The portal has also added a reCAPTCHA to its
search box, which is a clear signal about automated access.

Whether Vercel's egress is allowed can only be answered by the `?diagnose=1`
call above. If it comes back blocked, route requests through a fetch proxy by
setting one environment variable — no code changes:

```
INSPECTIONS_PROXY_TEMPLATE=https://api.scraperapi.com/?api_key=YOUR_KEY&url={url}
```

Any service that fetches a URL for you works; `{url}` is replaced with the
URL-encoded target. Free tiers are far more than enough — a weekly digest is
about a dozen requests.

## Notes and limits

- **Deployment file list.** `.github/workflows/daily.yml` uploads an explicit
  set of files to Vercel. It now walks `api/` and `lib/` so the functions ship
  with the site; before this change, that daily production deploy contained no
  functions at all.
- **No dedupe state.** The digest reports a rolling 7-day window. Vercel
  functions have no writable disk, so running it twice in one week sends
  overlapping content.
- **Violation parsing is best-effort.** The portal's printable report is parsed
  heuristically; when nothing recognizable is found, the reply links to the
  full report instead of inventing detail.
