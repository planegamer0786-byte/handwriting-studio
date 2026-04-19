import { useState, useCallback } from "react";
import type { StyleSettings, PaperTemplate, NoiseLevel, FontVariant } from "../lib/types";

const TEMPLATE_OPTIONS = [
  { value: "plain", label: "Plain Paper" },
  { value: "ruled", label: "Ruled Paper" },
  { value: "grid", label: "Grid Paper" },
  { value: "mjcet", label: "MJCET Answer Sheet" },
  { value: "mjcet_assignment", label: "MJCET Assignment Sheet" },
];

const NOISE_OPTIONS = [
  { value: "none", label: "None" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

const FONT_VARIANTS = [
  { value: "Regular", label: "Regular" },
  { value: "SemiBold", label: "SemiBold" },
  { value: "Bold", label: "Bold" },
];

interface SettingsPanelProps {
  settings: StyleSettings;
  onChange: (settings: StyleSettings) => void;
}

export default function SettingsPanel({ settings, onChange }: SettingsPanelProps) {
  const [collapsed, setCollapsed] = useState(false);

  const update = useCallback(
    <K extends keyof StyleSettings>(key: K, value: StyleSettings[K]) => {
      onChange({ ...settings, [key]: value });
    },
    [settings, onChange]
  );

  return (
    <aside className="settings-panel">
      <div className="settings-header" onClick={() => setCollapsed(!collapsed)}>
        <h3>Settings</h3>
        <span className="toggle">{collapsed ? "+" : "-"}</span>
      </div>

      {!collapsed && (
        <div className="settings-body">
          {/* Paper Template */}
          <div className="field">
            <label>Paper Template</label>
            <select
              value={settings.paper_template}
              onChange={(e) => update("paper_template", e.target.value as PaperTemplate)}
            >
              {TEMPLATE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Font Variant */}
          <div className="field">
            <label>Font Weight</label>
            <select
              value={settings.font_variant}
              onChange={(e) => update("font_variant", e.target.value as FontVariant)}
            >
              {FONT_VARIANTS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Font Size */}
          <div className="field">
            <label>Font Size: {settings.font_size}px</label>
            <input
              type="range"
              min={14}
              max={72}
              value={settings.font_size}
              onChange={(e) => update("font_size", Number(e.target.value))}
            />
          </div>

          {/* Line Spacing */}
          <div className="field">
            <label>Line Spacing: {settings.line_spacing.toFixed(2)}x</label>
            <input
              type="range"
              min={10}
              max={30}
              value={Math.round(settings.line_spacing * 10)}
              onChange={(e) => update("line_spacing", Number(e.target.value) / 10)}
            />
          </div>

          {/* Noise Level */}
          <div className="field">
            <label>Handwriting Noise</label>
            <select
              value={settings.noise_level}
              onChange={(e) => update("noise_level", e.target.value as NoiseLevel)}
            >
              {NOISE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Scanner Effect */}
          <div className="field row">
            <label>Scanner Effect</label>
            <input
              type="checkbox"
              checked={settings.enable_scanner_effect}
              onChange={(e) => update("enable_scanner_effect", e.target.checked)}
            />
          </div>

          {/* Page Slant */}
          <div className="field">
            <label>Page Slant: {settings.page_slant_deg.toFixed(1)} deg</label>
            <input
              type="range"
              min={-30}
              max={30}
              value={Math.round(settings.page_slant_deg * 10)}
              onChange={(e) => update("page_slant_deg", Number(e.target.value) / 10)}
            />
          </div>

          {/* Ink Color */}
          <div className="field">
            <label>Ink Color</label>
            <input
              type="color"
              value={settings.ink_color}
              onChange={(e) => update("ink_color", e.target.value)}
            />
          </div>

          {/* Paper Color */}
          <div className="field">
            <label>Paper Color</label>
            <input
              type="color"
              value={settings.bg_color}
              onChange={(e) => update("bg_color", e.target.value)}
            />
          </div>

          {/* Margins */}
          <details className="advanced">
            <summary>Advanced Margins</summary>
            <div className="field">
              <label>Top: {settings.margin_top}px</label>
              <input
                type="range"
                min={20}
                max={350}
                value={settings.margin_top}
                onChange={(e) => update("margin_top", Number(e.target.value))}
              />
            </div>
            <div className="field">
              <label>Left: {settings.margin_left}px</label>
              <input
                type="range"
                min={20}
                max={250}
                value={settings.margin_left}
                onChange={(e) => update("margin_left", Number(e.target.value))}
              />
            </div>
            <div className="field">
              <label>Right: {settings.margin_right}px</label>
              <input
                type="range"
                min={10}
                max={200}
                value={settings.margin_right}
                onChange={(e) => update("margin_right", Number(e.target.value))}
              />
            </div>
            <div className="field">
              <label>Bottom: {settings.margin_bottom}px</label>
              <input
                type="range"
                min={20}
                max={250}
                value={settings.margin_bottom}
                onChange={(e) => update("margin_bottom", Number(e.target.value))}
              />
            </div>
          </details>
        </div>
      )}
    </aside>
  );
}
