//! ChapterModel: 相対時間チャプターと除外区間。
//! Python 実装（chaptr/ui/models.py: ChapterInfo, compute_excluded_regions）を移植。
//! 「-- プレフィックス」で除外区間を表す仕様、相対時間方式を踏襲。

#[derive(Debug, Clone, PartialEq)]
pub struct ChapterInfo {
    /// ソースファイル内のローカル時間（ミリ秒）。
    pub local_time_ms: i64,
    pub title: String,
    /// 所属ソースのインデックス（単一ソースなら None）。
    pub source_index: Option<usize>,
}

impl ChapterInfo {
    pub fn new(local_time_ms: i64, title: impl Into<String>, source_index: Option<usize>) -> Self {
        Self {
            local_time_ms,
            title: title.into(),
            source_index,
        }
    }

    /// 除外チャプターか（`--` プレフィックス）。
    pub fn is_excluded(&self) -> bool {
        self.title.starts_with("--")
    }

    /// 累積時間（絶対時間）を計算。source_offsets は各ソースの開始オフセット(ms)。
    pub fn absolute_time_ms(&self, source_offsets: &[i64]) -> i64 {
        match self.source_index {
            Some(idx) if idx < source_offsets.len() => source_offsets[idx] + self.local_time_ms,
            _ => self.local_time_ms,
        }
    }
}

/// 除外チャプター（`--`）の区間 (start_ms, end_ms) を計算。
///
/// 区間は「-- チャプター開始 → 時刻が厳密に大きい最初のチャプター開始」、無ければ
/// メディア終端まで。同時刻チャプターで幅0になるのを避けるため、厳密大の最初まで飛ばす。
/// （chaptr/ui/models.py: compute_excluded_regions と同一仕様）
pub fn compute_excluded_regions(chapters: &[ChapterInfo], duration_ms: i64) -> Vec<(i64, i64)> {
    if chapters.is_empty() || duration_ms <= 0 {
        return vec![];
    }
    let mut sorted: Vec<&ChapterInfo> = chapters.iter().collect();
    sorted.sort_by_key(|c| c.local_time_ms);

    let mut out = Vec::new();
    for (i, ch) in sorted.iter().enumerate() {
        if ch.title.starts_with("--") {
            let start = ch.local_time_ms;
            let mut end = duration_ms;
            for nxt in &sorted[i + 1..] {
                if nxt.local_time_ms > start {
                    end = nxt.local_time_ms;
                    break;
                }
            }
            out.push((start, end));
        }
    }
    out
}

/// ミリ秒を HH:MM:SS.mmm に整形（chaptr/ui/models.py: _format_time_ms 相当）。
pub fn format_time_ms(time_ms: i64, include_ms: bool) -> String {
    let time_ms = time_ms.max(0);
    let total_sec = time_ms / 1000;
    let ms = time_ms % 1000;
    let h = total_sec / 3600;
    let m = (total_sec % 3600) / 60;
    let s = total_sec % 60;
    if include_ms {
        format!("{}:{:02}:{:02}.{:03}", h, m, s, ms)
    } else {
        format!("{}:{:02}:{:02}", h, m, s)
    }
}
