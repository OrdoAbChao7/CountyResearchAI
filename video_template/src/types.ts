export interface SubtitleItem {
  index: number;
  segment_id: string;
  text: string;
  start_ms: number;
  end_ms: number;
}

export interface SegmentProp {
  segment_id: string;
  time_range: string;
  narration: string;
  on_screen: string;
  visual_hint: string;
  source_refs?: string[];
  duration_ms: number;
  start_offset_ms: number;
  end_offset_ms: number;
  image_url?: string;
}

export interface VideoProps {
  county: string;
  title: string;
  hook: string;
  perspective: string;
  total_duration_ms: number;
  audio_url: string;
  bgm_url?: string;
  sfx_url?: string;
  theme?: string;
  segments: SegmentProp[];
  subtitles: SubtitleItem[];
}

