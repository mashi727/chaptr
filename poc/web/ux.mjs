// UX 実測: 複数ビューポートでスクショ + 触覚UX指標の計測
import http from 'http';
import { readFileSync, existsSync } from 'fs';
import { extname, join } from 'path';
import { chromium } from 'playwright';

const ROOT = '/home/user/chaptr/poc/web';
const OUT = '/home/user/chaptr/poc/web';
const MIME = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css' };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]); if (p === '/') p = '/index.html';
  const f = join(ROOT, p);
  if (!existsSync(f)) { res.writeHead(404); res.end('nf'); return; }
  res.writeHead(200, { 'Content-Type': MIME[extname(f)] || 'application/octet-stream' });
  res.end(readFileSync(f));
});
await new Promise((r) => server.listen(0, r));
const base = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch({
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
  args: ['--autoplay-policy=no-user-gesture-required', '--no-sandbox'] });

const devices = [
  { name: 'iphone-portrait',  w: 390, h: 844,  touch: true },
  { name: 'ipad-portrait',    w: 834, h: 1112, touch: true },
  { name: 'ipad-landscape',   w: 1194, h: 834, touch: true },
];

const report = {};
for (const d of devices) {
  const ctx = await browser.newContext({
    viewport: { width: d.w, height: d.h },
    hasTouch: d.touch, isMobile: d.touch, deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.evaluate(() => window.__loadSynthetic(30));
  // チャプターを2つ打って実利用に近い状態に
  await page.click('#p100'); await page.waitForTimeout(40); await page.click('#addch');
  await page.click('#p100'); await page.waitForTimeout(40); await page.click('#p100'); await page.waitForTimeout(40); await page.click('#addch');
  await page.waitForTimeout(150);

  // --- 触覚UX指標の計測 ---
  const m = await page.evaluate(() => {
    const vw = innerWidth, vh = innerHeight;
    const header = document.querySelector('header').getBoundingClientRect();
    const aside = document.querySelector('aside').getBoundingClientRect();
    const wf = document.getElementById('waveform').getBoundingClientRect();
    const sp = document.getElementById('spectro').getBoundingClientRect();
    // ボタンのタッチターゲット計測
    const btns = [...document.querySelectorAll('button, label.btn')];
    const heights = btns.map(b => b.getBoundingClientRect().height);
    const minH = Math.min(...heights), under44 = heights.filter(h => h < 44).length;
    // 横はみ出し（行内ボタンが viewport を超える）
    const overflowX = btns.some(b => { const r = b.getBoundingClientRect(); return r.right > vw + 0.5 || r.left < -0.5; });
    // ヘッダ占有率
    const headerPct = Math.round((header.height / vh) * 100);
    // 波形+スペクトロの合計高さ占有率
    const stagePct = Math.round(((wf.height + sp.height) / vh) * 100);
    return {
      vw, vh, headerPx: Math.round(header.height), headerPct, asidePx: Math.round(aside.height),
      wfH: Math.round(wf.height), spH: Math.round(sp.height), stagePct,
      btnMinH: Math.round(minH), btnUnder44: under44, btnTotal: btns.length, overflowX,
    };
  });
  report[d.name] = m;
  await page.screenshot({ path: join(OUT, `ux-${d.name}.png`) });
  await ctx.close();
}
await browser.close(); server.close();
console.log(JSON.stringify(report, null, 2));
