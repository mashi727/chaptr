// app.js - PoC 本体（4機能 + 2大リスクの検証 UI）
//
// 検証対象:
//   [機能] 波形 / スペクトログラム / ms再生制御 / チャプター作成
//   [リスク1] ms 再生クロックの精度（位置表示・ナッジ・シーク）
//   [リスク2] 長尺スペクトログラムの可視範囲オンデマンド計算が一定コストか
//
// すべて単一の static ファイル群で完結。iPad Safari でそのまま開ける。

import { PlayerClock } from './player.js';
import {
  buildPeakPyramid, peaksForView, stftView, infernoLUT, toMono, normalizePeaks, fftRadix2,
} from './dsp.js';

// テスト用にコア DSP を公開
window.__dsp = { buildPeakPyramid, peaksForView, stftView, fftRadix2, infernoLUT };

const $ = (id) => document.getElementById(id);
const LUT = infernoLUT();

const state = {
  audioBuffer: null,
  sr: 48000,
  mono: null,
  pyramid: null,
  view: { t0: 0, t1: 0 },     // 表示時間範囲（秒）
  duration: 0,
  chapters: [],               // { ms, title }
  lastStftMs: 0,
  fps: 0,
};
const player = new PlayerClock();

// ============================================================
// オーディオ読み込み
// ============================================================
async function loadAudioBuffer(buffer) {
  state.audioBuffer = buffer;
  state.sr = buffer.sampleRate;
  state.duration = buffer.duration;
  const mono = toMono(buffer);
  state.mono = normalizePeaks(mono);
  const t0 = performance.now();
  state.pyramid = buildPeakPyramid(state.mono, 256);
  const buildMs = performance.now() - t0;
  state.view = { t0: 0, t1: state.duration };
  state.chapters = [];
  player.setBuffer(buffer);
  $('info').textContent =
    `読み込み完了: ${state.duration.toFixed(2)}s / ${state.sr}Hz / ` +
    `${buffer.numberOfChannels}ch / LODピラミッド構築 ${buildMs.toFixed(0)}ms ` +
    `(${state.pyramid.mins.length.toLocaleString()} buckets)`;
  invalidateSpectrogram();
  redrawAll();
  renderChapters();
}

async function decodeFile(file) {
  const ab = await file.arrayBuffer();
  const ctx = await player.ensureContext();
  const buf = await ctx.decodeAudioData(ab);
  await loadAudioBuffer(buf);
}

// 合成チャープ（ファイル無しでも検証できるよう）: 周波数が時間で上昇 + クリック音
function makeSyntheticBuffer(seconds = 30, sr = 48000) {
  const ctx = player.ctx || new (window.AudioContext || window.webkitAudioContext)();
  player.ctx = ctx;
  const n = Math.floor(seconds * sr);
  const buf = ctx.createBuffer(1, n, sr);
  const d = buf.getChannelData(0);
  let phase = 0;
  for (let i = 0; i < n; i++) {
    const t = i / sr;
    const f = 200 + (3000 - 200) * (t / seconds);   // 200→3000Hz チャープ
    phase += (2 * Math.PI * f) / sr;
    let v = 0.5 * Math.sin(phase);
    v += 0.2 * Math.sin(2 * Math.PI * 440 * t);       // 440Hz 定常
    if (i % sr < 2) v += 0.9;                          // 毎秒クリック（ms精度の聴覚確認用）
    d[i] = v;
  }
  return buf;
}

// ============================================================
// 描画: 波形
// ============================================================
function drawWaveform() {
  const cv = $('waveform');
  const ctx = cv.getContext('2d');
  const w = cv.width, h = cv.height, cy = h / 2;
  ctx.fillStyle = '#11131a';
  ctx.fillRect(0, 0, w, h);
  if (!state.pyramid) return;
  const s0 = Math.floor(state.view.t0 * state.sr);
  const s1 = Math.ceil(state.view.t1 * state.sr);
  const peaks = peaksForView(state.pyramid, s0, s1, w);
  ctx.strokeStyle = '#4caf6a';
  ctx.beginPath();
  for (let x = 0; x < w; x++) {
    const mn = peaks[x * 2], mx = peaks[x * 2 + 1];
    const peak = Math.max(Math.abs(mn), Math.abs(mx));
    const bh = peak * (h - 6) / 2;
    ctx.moveTo(x + 0.5, cy - bh);
    ctx.lineTo(x + 0.5, cy + bh);
  }
  ctx.stroke();
  drawOverlays(ctx, w, h);
}

// ============================================================
// 描画: スペクトログラム（可視範囲オンデマンド + キャッシュ）
// ============================================================
let _spectroCache = null; // { key, image }
function invalidateSpectrogram() { _spectroCache = null; }

function drawSpectrogram() {
  const cv = $('spectro');
  const ctx = cv.getContext('2d');
  const w = cv.width, h = cv.height;
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, w, h);
  if (!state.mono) return;

  const key = `${state.view.t0.toFixed(4)}_${state.view.t1.toFixed(4)}_${w}x${h}`;
  if (!_spectroCache || _spectroCache.key !== key) {
    const fftSize = 2048;
    const t0 = performance.now();
    const { mag, cols, bins } = stftView(state.mono, state.sr, state.view.t0, state.view.t1, w, fftSize);
    state.lastStftMs = performance.now() - t0;
    // 周波数ビン → 縦方向（対数軸: 低音を広く）
    const img = ctx.createImageData(w, h);
    const maxBin = bins - 1;
    for (let y = 0; y < h; y++) {
      // 画面下=低周波, 上=高周波。対数マッピング。
      const frac = 1 - y / h;
      const bin = Math.min(maxBin, Math.round(Math.pow(frac, 2.0) * maxBin));
      for (let x = 0; x < cols; x++) {
        let v = mag[x * bins + bin];
        v = Math.pow(v, 0.8); // ガンマ（waveform.py と同様）
        const li = Math.min(255, Math.max(0, (v * 255) | 0)) * 3;
        const o = (y * w + x) * 4;
        img.data[o] = LUT[li];
        img.data[o + 1] = LUT[li + 1];
        img.data[o + 2] = LUT[li + 2];
        img.data[o + 3] = 255;
      }
    }
    _spectroCache = { key, image: img };
    $('perf').textContent =
      `STFT(可視範囲のみ) ${state.lastStftMs.toFixed(1)}ms / ${w}列 / fftSize=${fftSize} ` +
      `｜ 表示 ${(state.view.t1 - state.view.t0).toFixed(2)}s / 総尺 ${state.duration.toFixed(0)}s`;
  }
  ctx.putImageData(_spectroCache.image, 0, 0);
  drawOverlays(ctx, w, h);
}

// 共通オーバーレイ（チャプター線・再生位置）
function drawOverlays(ctx, w, h) {
  const dur = state.view.t1 - state.view.t0;
  if (dur <= 0) return;
  // チャプター
  ctx.strokeStyle = 'rgba(137,195,235,0.9)';
  ctx.lineWidth = 1.5;
  for (const ch of state.chapters) {
    const t = ch.ms / 1000;
    if (t < state.view.t0 || t > state.view.t1) continue;
    const x = ((t - state.view.t0) / dur) * w;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  // 再生位置
  const pt = player.positionSec;
  if (pt >= state.view.t0 && pt <= state.view.t1) {
    const x = ((pt - state.view.t0) / dur) * w;
    ctx.strokeStyle = '#ff5252'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
}

function redrawAll() { drawWaveform(); drawSpectrogram(); }

// ============================================================
// 時間表示
// ============================================================
function fmt(ms) {
  ms = Math.max(0, ms);
  const t = Math.floor(ms / 1000);
  const mm = String(Math.floor(t / 60)).padStart(2, '0');
  const ss = String(t % 60).padStart(2, '0');
  const mmm = String(Math.floor(ms % 1000)).padStart(3, '0');
  return `${mm}:${ss}.${mmm}`;
}

// ============================================================
// アニメーションループ（再生位置・FPS）
// ============================================================
let _frames = 0, _fpsT = performance.now();
function tick() {
  $('pos').textContent = fmt(player.positionMs);
  $('posms').textContent = `${player.positionMs.toFixed(1)} ms`;
  // 再生中のみ再生位置オーバーレイを更新（軽量化のため波形は再描画せず線だけ重ねる）
  if (player.isPlaying) redrawAll();
  _frames++;
  const now = performance.now();
  if (now - _fpsT >= 500) {
    state.fps = Math.round((_frames * 1000) / (now - _fpsT));
    $('fps').textContent = `${state.fps} fps`;
    _frames = 0; _fpsT = now;
  }
  requestAnimationFrame(tick);
}

// ============================================================
// ズーム / スクロール（共有タイムライン）
// ============================================================
function zoomAt(factor, centerFrac) {
  const { t0, t1 } = state.view;
  const span = t1 - t0;
  const center = t0 + span * centerFrac;
  let ns = Math.max(0.02, Math.min(state.duration, span * factor));
  let nt0 = center - ns * centerFrac;
  let nt1 = nt0 + ns;
  if (nt0 < 0) { nt0 = 0; nt1 = ns; }
  if (nt1 > state.duration) { nt1 = state.duration; nt0 = Math.max(0, nt1 - ns); }
  state.view = { t0: nt0, t1: nt1 };
  invalidateSpectrogram();
  redrawAll();
}
function scrollBy(fracOfView) {
  const span = state.view.t1 - state.view.t0;
  let d = span * fracOfView;
  let nt0 = state.view.t0 + d, nt1 = state.view.t1 + d;
  if (nt0 < 0) { nt1 -= nt0; nt0 = 0; }
  if (nt1 > state.duration) { nt0 -= (nt1 - state.duration); nt1 = state.duration; }
  state.view = { t0: Math.max(0, nt0), t1: Math.min(state.duration, nt1) };
  invalidateSpectrogram();
  redrawAll();
}

// ============================================================
// チャプター
// ============================================================
function addChapterAtPlayhead() {
  const ms = Math.round(player.positionMs);
  state.chapters.push({ ms, title: `Chapter ${state.chapters.length + 1}` });
  state.chapters.sort((a, b) => a.ms - b.ms);
  renderChapters();
  redrawAll();
}
function renderChapters() {
  const ul = $('chapters');
  ul.innerHTML = '';
  state.chapters.forEach((ch, i) => {
    const li = document.createElement('li');
    li.innerHTML = `<span class="t" data-i="${i}">${fmt(ch.ms)}</span> ` +
      `<input data-i="${i}" value="${ch.title.replace(/"/g, '&quot;')}"> ` +
      `<button data-del="${i}">✕</button>`;
    ul.appendChild(li);
  });
}
function exportVce() {
  const obj = {
    version: '2.0',
    sources: [{ path: 'poc-source', start: 0, end: Math.round(state.duration * 1000) }],
    chapters: state.chapters.map((c, i) => {
      const end = i + 1 < state.chapters.length ? state.chapters[i + 1].ms : Math.round(state.duration * 1000);
      return { title: c.title, start: c.ms, end };
    }),
  };
  download('project.vce.json', JSON.stringify(obj, null, 2));
}
function exportYouTube() {
  const lines = state.chapters.map((c) => {
    const t = Math.floor(c.ms / 1000);
    const hh = Math.floor(t / 3600), mm = Math.floor((t % 3600) / 60), ss = t % 60;
    const ts = hh > 0 ? `${hh}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`
      : `${mm}:${String(ss).padStart(2, '0')}`;
    return `${ts} ${c.title}`;
  });
  download('youtube-chapters.txt', lines.join('\n'));
}
function download(name, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
  a.download = name; a.click();
}

// ============================================================
// イベント結線
// ============================================================
function wire() {
  $('file').addEventListener('change', (e) => { if (e.target.files[0]) decodeFile(e.target.files[0]); });
  $('synth').addEventListener('click', async () => {
    const secs = parseInt($('synthlen').value || '30', 10);
    await loadAudioBuffer(makeSyntheticBuffer(secs, 48000));
  });
  $('play').addEventListener('click', async () => {
    if (player.isPlaying) { player.pause(); $('play').textContent = '▶'; }
    else { await player.play(); $('play').textContent = '⏸'; }
  });
  for (const [id, d] of [['m100', -100], ['m10', -10], ['p10', 10], ['p100', 100]]) {
    $(id).addEventListener('click', () => player.nudgeMs(d).then(redrawAll));
  }
  $('addch').addEventListener('click', addChapterAtPlayhead);
  $('zoomin').addEventListener('click', () => zoomAt(0.5, 0.5));
  $('zoomout').addEventListener('click', () => zoomAt(2.0, 0.5));
  $('zoomfit').addEventListener('click', () => { state.view = { t0: 0, t1: state.duration }; invalidateSpectrogram(); redrawAll(); });
  $('left').addEventListener('click', () => scrollBy(-0.25));
  $('right').addEventListener('click', () => scrollBy(0.25));
  $('expvce').addEventListener('click', exportVce);
  $('expyt').addEventListener('click', exportYouTube);

  // 波形/スペクトログラムのクリック=シーク、ドラッグ=スクラブ
  for (const id of ['waveform', 'spectro']) {
    const cv = $(id);
    const seekFromEvent = (e) => {
      const r = cv.getBoundingClientRect();
      const frac = (e.clientX - r.left) / r.width;
      const t = state.view.t0 + frac * (state.view.t1 - state.view.t0);
      player.seekMs(t * 1000).then(redrawAll);
    };
    cv.addEventListener('pointerdown', (e) => { cv.setPointerCapture(e.pointerId); seekFromEvent(e); cv._drag = true; });
    cv.addEventListener('pointermove', (e) => { if (cv._drag) seekFromEvent(e); });
    cv.addEventListener('pointerup', (e) => { cv._drag = false; });
    // ホイールズーム
    cv.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = cv.getBoundingClientRect();
      const frac = (e.clientX - r.left) / r.width;
      zoomAt(e.deltaY > 0 ? 1.25 : 0.8, frac);
    }, { passive: false });
  }

  // チャプター編集
  $('chapters').addEventListener('input', (e) => {
    const i = e.target.dataset.i; if (i != null) state.chapters[i].title = e.target.value;
  });
  $('chapters').addEventListener('click', (e) => {
    if (e.target.dataset.del != null) {
      state.chapters.splice(+e.target.dataset.del, 1); renderChapters(); redrawAll();
    } else if (e.target.dataset.i != null && e.target.classList.contains('t')) {
      player.seekMs(state.chapters[+e.target.dataset.i].ms).then(redrawAll);
    }
  });
  player.onEnded = () => { $('play').textContent = '▶'; };

  // リサイズ対応
  const ro = new ResizeObserver(() => { sizeCanvases(); invalidateSpectrogram(); redrawAll(); });
  ro.observe($('stage'));
}

function sizeCanvases() {
  for (const id of ['waveform', 'spectro']) {
    const cv = $(id);
    const r = cv.getBoundingClientRect();
    cv.width = Math.max(100, Math.floor(r.width));
    cv.height = Math.max(60, Math.floor(r.height));
  }
}

// テスト用フック: 合成バッファを直接ロード
window.__loadSynthetic = async (secs) => { await loadAudioBuffer(makeSyntheticBuffer(secs || 30, 48000)); return true; };

window.addEventListener('DOMContentLoaded', () => {
  wire();
  sizeCanvases();
  tick();
});
