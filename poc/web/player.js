// player.js - ms レベル再生クロック（PoC-1 の中核）
//
// 設計書 §6.3 の要点を Web Audio で実装:
//   - 高レベルプレイヤーの seek 精度に依存しない
//   - 再生位置 = AudioContext の高精度クロック（currentTime, サブms分解能）
//   - シークは AudioBufferSourceNode を offset 付きで再スケジュール（サンプル精度）
//
// Tauri(Rust/cpal) / Flutter / Swift(AVAudioEngine) でも同じ契約
// （PlayerClock: 再生位置をサンプルカウンタで提供）に置き換え可能。

export class PlayerClock {
  constructor() {
    this.ctx = null;
    this.buffer = null;
    this.source = null;
    this._playing = false;
    this._posSec = 0;        // 一時停止中に保持する位置
    this._startCtxTime = 0;  // 再生開始時の ctx.currentTime
    this._startOffset = 0;   // 再生開始時の位置（秒）
  }

  async ensureContext() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (this.ctx.state === 'suspended') {
      await this.ctx.resume(); // iOS Safari: ユーザー操作起点で resume が必要
    }
    return this.ctx;
  }

  setBuffer(buffer) {
    this.stop();
    this.buffer = buffer;
    this._posSec = 0;
  }

  get duration() { return this.buffer ? this.buffer.duration : 0; }
  get isPlaying() { return this._playing; }

  // 現在位置（秒）。再生中は ctx の高精度クロックから算出（サブms）。
  get positionSec() {
    if (this._playing && this.ctx) {
      const p = this._startOffset + (this.ctx.currentTime - this._startCtxTime);
      return Math.min(this.duration, Math.max(0, p));
    }
    return this._posSec;
  }
  get positionMs() { return this.positionSec * 1000; }

  async play() {
    if (!this.buffer || this._playing) return;
    await this.ensureContext();
    const src = this.ctx.createBufferSource();
    src.buffer = this.buffer;
    src.connect(this.ctx.destination);
    const offset = Math.min(this._posSec, this.duration);
    this._startCtxTime = this.ctx.currentTime;
    this._startOffset = offset;
    src.start(0, offset); // offset は秒（float）→ サンプル精度で開始
    src.onended = () => {
      // 自然終了（シーク等での停止と区別するためフラグ確認）
      if (this._playing && this.source === src) {
        this._playing = false;
        this._posSec = this.duration;
        if (this.onEnded) this.onEnded();
      }
    };
    this.source = src;
    this._playing = true;
  }

  pause() {
    if (!this._playing) return;
    this._posSec = this.positionSec; // 停止前に現在位置を確定
    this._stopSource();
    this._playing = false;
  }

  stop() {
    this._stopSource();
    this._playing = false;
    this._posSec = 0;
  }

  _stopSource() {
    if (this.source) {
      try { this.source.onended = null; this.source.stop(); } catch (e) {}
      this.source = null;
    }
  }

  // 任意 ms へシーク（サンプル精度）。再生中なら再スケジュール。
  // 位置確定（_posSec）は同期で行い、連続呼び出しでも基準位置がずれないようにする。
  async seekMs(ms) {
    const sec = Math.min(this.duration, Math.max(0, ms / 1000));
    const wasPlaying = this._playing;
    this._stopSource();
    this._playing = false;
    this._posSec = sec;          // ← 同期確定（後続 nudge はこの値を基準に読む）
    if (wasPlaying) await this.play();
  }

  // 相対ナッジ（±ms）。基準位置を同期で確定してから（必要なら）再生を再開。
  // 連続ナッジ（+10,+10,...）でも各呼び出しが直前の確定値を基準にできる。
  nudgeMs(delta) {
    return this.seekMs(this.positionMs + delta);
  }
}
