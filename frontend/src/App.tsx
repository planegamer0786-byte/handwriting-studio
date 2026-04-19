import { useState, useCallback } from "react";
import type { StyleSettings, PreviewResponse, ExportStatusResponse } from "./lib/types";
import SettingsPanel from "./components/SettingsPanel";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const DEFAULT_SETTINGS: StyleSettings = {
  font_variant: "Regular",
  font_size: 36,
  ink_color: "#1a1a2e",
  bg_color: "#ffffff",
  line_spacing: 1.65,
  margin_top: 110,
  margin_left: 75,
  margin_right: 50,
  margin_bottom: 60,
  noise_level: "medium",
  baseline_jitter: 2.5,
  pressure_variance: 0.15,
  rotation_jitter: 1.2,
  word_spacing_variance: 0.15,
  paper_template: "mjcet_assignment",
  enable_scanner_effect: true,
  page_slant_deg: 0.3,
};

const SAMPLE_TEXT = `Network Security

Definition: The practice of protecting systems and data from unauthorized access or attacks.

Key concepts include:
- Encryption: scrambling data so only authorized parties can read it
- Authentication: verifying the identity of users and devices
- Firewalls: monitoring and controlling incoming and outgoing network traffic
- Intrusion Detection Systems: identifying suspicious activity on a network
- VPNs: creating secure encrypted connections over public networks

Security is essential in today's connected world where cyber threats are constantly evolving and becoming more sophisticated.`;

export default function App() {
  const [text, setText] = useState(SAMPLE_TEXT);
  const [settings, setSettings] = useState<StyleSettings>(DEFAULT_SETTINGS);
  const [preview, setPreview] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportJob, setExportJob] = useState<ExportStatusResponse | null>(null);
  const [renderTime, setRenderTime] = useState(0);

  const handlePreview = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, settings }),
      });
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const data: PreviewResponse = await res.json();
      setPreview(data.image);
      setRenderTime(data.render_ms);
    } catch (e: any) {
      setError(e.message || "Preview failed");
    } finally {
      setLoading(false);
    }
  }, [text, settings]);

  const handleExport = useCallback(
    async (format: "png" | "pdf") => {
      setExporting(true);
      setError("");
      try {
        const res = await fetch(`${API_URL}/api/export`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text,
            settings,
            output_format: format,
            resolution_scale: 1.0,
          }),
        });
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        const data: ExportStatusResponse = await res.json();
        setExportJob(data);

        // Poll for completion
        const poll = setInterval(async () => {
          const statusRes = await fetch(`${API_URL}/api/export/${data.job_id}`);
          const status: ExportStatusResponse = await statusRes.json();
          setExportJob(status);
          if (status.status === "done" || status.status === "failed") {
            clearInterval(poll);
            setExporting(false);
            if (status.status === "done" && status.download_url) {
              window.open(`${API_URL}${status.download_url}`, "_blank");
            }
          }
        }, 1500);
      } catch (e: any) {
        setError(e.message || "Export failed");
        setExporting(false);
      }
    },
    [text, settings]
  );

  return (
    <div className="app">
      <header className="app-header">
        <h1>Handwriting Studio</h1>
        <p>Convert typed text into realistic handwritten notes</p>
      </header>

      <div className="app-body">
        <SettingsPanel settings={settings} onChange={setSettings} />

        <main className="main-area">
          <div className="editor-section">
            <label className="editor-label">Your Text</label>
            <textarea
              className="text-input"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={12}
              placeholder="Type or paste your text here..."
            />

            <div className="actions">
              <button
                className="btn btn-primary"
                onClick={handlePreview}
                disabled={loading || !text.trim()}
              >
                {loading ? "Rendering..." : "Preview"}
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => handleExport("png")}
                disabled={exporting || !text.trim()}
              >
                Export PNG
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => handleExport("pdf")}
                disabled={exporting || !text.trim()}
              >
                Export PDF
              </button>
            </div>

            {error && <div className="error">{error}</div>}

            {exportJob && (
              <div className="export-status">
                Export: {exportJob.status}
                {exportJob.status === "rendering" && (
                  <div className="progress-bar">
                    <div
                      className="progress-fill"
                      style={{ width: `${exportJob.progress}%` }}
                    />
                  </div>
                )}
              </div>
            )}
          </div>

          {preview && (
            <div className="preview-section">
              <div className="preview-header">
                <span>Preview</span>
                {renderTime > 0 && (
                  <span className="render-time">{renderTime}ms</span>
                )}
              </div>
              <img
                src={`data:image/jpeg;base64,${preview}`}
                alt="Handwriting preview"
                className="preview-image"
              />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
