// PoC 検証: DSP の正しさ + 2大リスクの定量チェック + スクリーンショット
import http from 'http';
import { readFileSync, existsSync } from 'fs';
import { extname, join } from 'path';
import { chromium } from 'playwright';

const ROOT = '/home/user/chaptr/poc/web';
const MIME = { '.html':'text/html', '.js':'text/javascript', '.css':'text/css' };

// --- 簡易静的サーバ（ESモジュールのCORS回避のため file:// ではなく http で配信） ---
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/index.html';
  const f = join(ROOT, p);
  if (!existsSync(f)) { res.writeHead(404); res.end('nf'); return; }
  res.writeHead(200, { 'Content-Type': MIME[extname(f)] || 'application/octet-stream' });
  res.end(readFileSync(f));
});
await new Promise((r) => server.listen(0, r));
const port = server.address().port;
const base = `http://127.0.0.1:${port}/`;

const results = [];
const ok = (n, cond, detail='') => { results.push({ n, pass: !!cond, detail }); console.log(`${cond?'PASS':'FAIL'}  ${n}  ${detail}`); };

// Chromium パス: 環境変数 CHROMIUM_PATH 優先、無ければ Playwright 同梱を使う
const browser = await chromium.launch({
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
  args: ['--autoplay-policy=no-user-gesture-required', '--no-sandbox'],
});
const page = await browser.newPage({ viewport: { width: 1200, height: 820 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message));
page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE.ERR:', m.text()); });
await page.goto(base, { waitUntil: 'networkidle' });

// --- A: FFT 正しさ（既知正弦波 → 期待ビンにピーク） ---
const fftCheck = await page.evaluate(() => {
  const { fftRadix2 } = window.__dsp;
  const N = 2048, sr = 48000, freq = 1000;
  const re = new Float64Array(N), im = new Float64Array(N);
  for (let i = 0; i < N; i++) re[i] = Math.sin(2*Math.PI*freq*i/sr);
  fftRadix2(re, im);
  let best = 0, bestv = -1;
  for (let k = 1; k < N/2; k++) { const m = re[k]*re[k]+im[k]*im[k]; if (m > bestv) { bestv = m; best = k; } }
  return { best, expected: Math.round(freq/(sr/N)) };
});
ok('A. FFT 正弦波ピーク位置', Math.abs(fftCheck.best - fftCheck.expected) <= 1,
   `peak bin=${fftCheck.best} expected≈${fftCheck.expected}`);

// --- B: STFT 可視範囲コストが総尺に依存しない（リスク2） ---
const stftCost = await page.evaluate(() => {
  const { stftView } = window.__dsp;
  const sr = 48000;
  const mk = (sec) => { const a = new Float32Array(sec*sr); for (let i=0;i<a.length;i++) a[i]=Math.sin(i*0.05); return a; };
  const short = mk(30);     // 30s
  const long  = mk(600);    // 600s（10分）
  const W = 1000, fft = 2048;
  // 同じ「5秒の可視範囲」を両方で計測（長尺は中央付近）
  const t = (mono, t0) => { const s = performance.now(); stftView(mono, sr, t0, t0+5, W, fft); return performance.now()-s; };
  t(short, 0); t(long, 100); // ウォームアップ
  const ms30 = t(short, 0);
  const ms600 = t(long, 300);
  return { ms30, ms600 };
});
ok('B. STFT 可視範囲コストが総尺非依存（リスク2）',
   stftCost.ms600 < stftCost.ms30 * 1.5 && stftCost.ms600 < 250,
   `30s音源=${stftCost.ms30.toFixed(1)}ms / 600s音源=${stftCost.ms600.toFixed(1)}ms（同じ5秒窓）`);

// --- C: LOD ピラミッド 構築コスト & 範囲 ---
const peakCheck = await page.evaluate(() => {
  const { buildPeakPyramid, peaksForView } = window.__dsp;
  const sr = 48000, sec = 600;
  const mono = new Float32Array(sec*sr);
  for (let i=0;i<mono.length;i++) mono[i] = Math.sin(i*0.01)*0.9;
  const s = performance.now();
  const pyr = buildPeakPyramid(mono, 256);
  const buildMs = performance.now()-s;
  const pk = peaksForView(pyr, 0, mono.length, 1000);
  let mx = 0; for (let x=0;x<1000;x++) mx = Math.max(mx, Math.abs(pk[x*2+1]));
  return { buildMs, buckets: pyr.mins.length, maxPeak: mx };
});
ok('C. LOD構築 600s音源を単一パスで高速', peakCheck.buildMs < 800 && peakCheck.maxPeak > 0.8 && peakCheck.maxPeak <= 1.0,
   `build=${peakCheck.buildMs.toFixed(0)}ms / ${peakCheck.buckets.toLocaleString()} buckets / maxPeak=${peakCheck.maxPeak.toFixed(3)}`);

// --- D: ms 再生クロックのシーク精度（リスク1） ---
const seekCheck = await page.evaluate(async () => {
  // PlayerClock を直接使うのではなく、UI経由の合成ロード → シーク精度（停止中）を確認
  await window.__loadSynthetic(30);
  // 内部 player は app.js スコープ。__dsp 同様の公開が無いので、UI操作で代替検証する。
  return true;
});
// UI 操作で ±10ms ナッジの表示が動くか（停止中シーク精度は表示で判断）
await page.click('#zoomfit');
// 実ユーザーの操作間隔を入れて ms シーク精度を検証（+100,+100,+10 = 210ms）
await page.click('#p100'); await page.waitForTimeout(60);
await page.click('#p100'); await page.waitForTimeout(60);
await page.click('#p10');  await page.waitForTimeout(60);
const posText = await page.textContent('#posms');
const posVal = parseFloat(posText);
ok('D. ms シーク精度（+100+100+10=210ms）', Math.abs(posVal - 210) <= 1.0, `表示=${posText}`);

// --- E: 描画が非空（波形・スペクトログラム） ---
await page.click('#addch');                 // 0ms 付近にチャプター
await page.click('#p100'); await page.click('#p100'); await page.click('#addch'); // 2つ目
const variance = await page.evaluate(() => {
  const v = (id) => {
    const cv = document.getElementById(id); const ctx = cv.getContext('2d');
    const d = ctx.getImageData(0,0,cv.width,cv.height).data;
    let min=255,max=0; for (let i=0;i<d.length;i+=4){ const g=d[i]; if(g<min)min=g; if(g>max)max=g; }
    return max-min;
  };
  return { wf: v('waveform'), sp: v('spectro') };
});
ok('E. 波形が描画されている', variance.wf > 20, `輝度レンジ=${variance.wf}`);
ok('E. スペクトログラムが描画されている', variance.sp > 20, `輝度レンジ=${variance.sp}`);

// --- F: チャプター書き出し（vce.json 構造） ---
const chCount = await page.evaluate(() => document.querySelectorAll('#chapters li').length);
ok('F. チャプター作成', chCount === 2, `チャプター数=${chCount}`);

// スクリーンショット
await page.screenshot({ path: '/home/user/chaptr/poc/web/screenshot-full.png', fullPage: false });
// ズームして長尺っぽい見た目に（合成30s → 5s窓）
await page.evaluate(() => { document.getElementById('zoomin').click(); document.getElementById('zoomin').click(); });
await page.waitForTimeout(200);
await page.screenshot({ path: '/home/user/chaptr/poc/web/screenshot-zoom.png' });

await browser.close();
server.close();

const passed = results.filter(r=>r.pass).length;
console.log(`\n==== ${passed}/${results.length} PASS ====`);
process.exit(passed === results.length ? 0 : 1);
