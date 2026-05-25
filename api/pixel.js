// Shared pixel handler — copy this to api/pixel.js in each Vercel project.
// Reads Host header to detect domain, increments count in domain-tracker repo.

const REPO  = "mach33v/domain-tracker";
const FILE  = "stats/counts.json";
const API   = "https://api.github.com";
// 1x1 transparent GIF
const GIF   = Buffer.from("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7", "base64");

export default async function handler(req, res) {
  // Always return the pixel immediately — don't make the visitor wait
  res.setHeader("Content-Type", "image/gif");
  res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");
  res.end(GIF);

  // Record the visit asynchronously (fire-and-forget from visitor's perspective)
  try {
    const domain = (req.headers.host || "unknown").replace(/^www\./, "");
    const today  = new Date().toISOString().split("T")[0];
    const token  = process.env.GITHUB_TOKEN;
    if (!token) return;

    // Fetch current counts
    const getRes = await fetch(`${API}/repos/${REPO}/contents/${FILE}`, {
      headers: { Authorization: `Bearer ${token}`, "User-Agent": "domain-tracker" }
    });
    const getJson = await getRes.json();
    const sha     = getJson.sha;
    const counts  = JSON.parse(Buffer.from(getJson.content, "base64").toString());

    // Increment
    if (!counts[domain]) counts[domain] = {};
    counts[domain][today] = (counts[domain][today] || 0) + 1;

    // Write back
    await fetch(`${API}/repos/${REPO}/contents/${FILE}`, {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "User-Agent": "domain-tracker"
      },
      body: JSON.stringify({
        message: `visit: ${domain} ${today}`,
        content: Buffer.from(JSON.stringify(counts, null, 2)).toString("base64"),
        sha
      })
    });
  } catch (e) {
    // Silently ignore — never break the page for a failed pixel
    console.error("pixel error:", e.message);
  }
}
