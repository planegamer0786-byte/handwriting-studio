// Paper template options
export type PaperTemplate = "plain" | "ruled" | "grid" | "mjcet" | "mjcet_assignment";

// Noise level options
export type NoiseLevel = "none" | "low" | "medium" | "high";

// Ink color presets
export type InkColor = "#1a1a2e" | "#000080" | "#006400" | "#8B0000" | "#4B0082";

// Font variant options
export type FontVariant = "Regular" | "SemiBold" | "Bold";

// Main settings object matching backend StyleSettings
export interface StyleSettings {
  font_variant: FontVariant;
  font_size: number;
  ink_color: string;
  bg_color: string;
  line_spacing: number;
  margin_top: number;
  margin_left: number;
  margin_right: number;
  margin_bottom: number;
  noise_level: NoiseLevel;
  baseline_jitter: number;
  pressure_variance: number;
  rotation_jitter: number;
  word_spacing_variance: number;
  paper_template: PaperTemplate;
  enable_scanner_effect: boolean;
  page_slant_deg: number;
}

// API request/response types
export interface PreviewRequest {
  text: string;
  settings: StyleSettings;
}

export interface PreviewResponse {
  image: string;
  pages: number;
  width: number;
  height: number;
  render_ms: number;
}

export interface ExportRequest {
  text: string;
  settings: StyleSettings;
  output_format: "png" | "pdf";
  resolution_scale: number;
}

export interface ExportStatusResponse {
  job_id: string;
  status: "queued" | "rendering" | "done" | "failed";
  progress: number;
  download_url: string;
  error: string;
}
