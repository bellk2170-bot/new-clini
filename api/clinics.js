// Vercel Serverless Function - new-clinics.csv 중계 (CORS 해결)
export default async function handler(req, res) {
  const url = 'https://raw.githubusercontent.com/bellk2170-bot/new-clini/main/new-clinics.csv';
  try {
    const r = await fetch(url, { headers: { 'User-Agent': 'vercel-proxy' } });
    if (!r.ok) { res.status(r.status).send('upstream error'); return; }
    const text = await r.text();
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Content-Type', 'text/csv; charset=utf-8');
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate');
    res.status(200).send(text);
  } catch(e) {
    res.status(500).send('fetch failed: ' + e.message);
  }
}
