/**
 * Sidebar — Viewer Controls & Case Info
 *
 * Extracted from App.tsx to reduce God Component complexity.
 * Reads state directly from Zustand store — no prop drilling.
 */

import { useViewerStore } from '../../stores/viewerStore';
import { PipelineVisualizer } from '../Pipeline/PipelineVisualizer';
import {
  RangeSlider,
  ToggleSwitch,
  SegmentedControl,
  InfoRow,
  Divider,
  Button,
} from '../UI';
import {
  WINDOW_PRESETS,
  type ViewMode,
  type WindowPresetKey,
} from '../../types';
import {
  FileText,
  Settings,
  Layers,
  Box,
  Info,
  LogOut,
  Eye,
  Palette,
  SlidersHorizontal,
} from 'lucide-react';

export function Sidebar() {
  const {
    metadata,
    pipelineSteps,
    viewMode,
    setViewMode,
    windowPreset,
    useCustomWindow,
    customWindowLevel,
    customWindowWidth,
    showSegmentation,
    segmentationOpacity,
    showWireframe,
    applyPreset,
    setUseCustomWindow,
    setCustomWindowLevel,
    setCustomWindowWidth,
    setShowSegmentation,
    setSegmentationOpacity,
    setShowWireframe,
    resetCase,
  } = useViewerStore();

  const viewModeOptions = [
    { value: '2D' as ViewMode, label: '2D', icon: <Layers size={14} /> },
    { value: '3D' as ViewMode, label: '3D', icon: <Box size={14} /> },
  ];

  const windowPresetOptions = Object.entries(WINDOW_PRESETS).map(([key, preset]) => ({
    value: key as WindowPresetKey,
    label: preset.name,
  }));

  const handleReset = () => {
    if (confirm('Are you sure you want to load a new case? Current progress will be lost.')) {
      resetCase();
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-lg)', height: '100%' }}>
      {/* Case Info Section */}
      <section>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-sm)',
            marginBottom: 'var(--space-md)',
          }}
        >
          <FileText size={16} color="var(--accent-primary)" />
          <h4 style={{ margin: 0 }}>Case Information</h4>
        </div>

        <div className="card">
          {metadata ? (
            <>
              <InfoRow label="Case ID" value={metadata.id.slice(0, 12) + '...'} mono />
              <InfoRow label="Slices" value={metadata.totalSlices} mono />
              <InfoRow label="Dimensions" value={metadata.dimensions.join(' × ')} mono />
              <InfoRow
                label="Spacing (mm)"
                value={metadata.voxelSpacing.map((v) => v.toFixed(2)).join(' × ')}
                mono
              />
              {metadata.huRange && (
                <InfoRow
                  label="HU Range"
                  value={`${metadata.huRange.min.toFixed(0)} ~ ${metadata.huRange.max.toFixed(0)}`}
                  mono
                />
              )}
              <Divider spacing="sm" />
              <Button
                variant="ghost"
                fullWidth
                icon={<LogOut size={14} />}
                onClick={handleReset}
                style={{ justifyContent: 'flex-start' }}
              >
                Load New Case
              </Button>
            </>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
              No active case
            </div>
          )}
        </div>
      </section>

      {/* View Settings Section */}
      <section>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-sm)',
            marginBottom: 'var(--space-md)',
          }}
        >
          <Settings size={16} color="var(--accent-primary)" />
          <h4 style={{ margin: 0 }}>View Settings</h4>
        </div>

        <div style={{ marginBottom: 'var(--space-md)' }}>
          <label style={{ marginBottom: 'var(--space-sm)' }}>Layout</label>
          <SegmentedControl
            options={viewModeOptions}
            value={viewMode}
            onChange={setViewMode}
          />
        </div>

        <div className="card">
          {/* CT Visualization Controls */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-sm)',
              marginBottom: 'var(--space-md)',
            }}
          >
            <Eye size={14} color="var(--text-muted)" />
            <span
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                textTransform: 'uppercase',
                color: 'var(--text-muted)',
                letterSpacing: '0.05em',
              }}
            >
              CT Visualization
            </span>
          </div>

          <div style={{ marginBottom: 'var(--space-md)' }}>
            <label style={{ marginBottom: 'var(--space-sm)' }}>Window Preset</label>
            <div style={{ display: 'flex', gap: 'var(--space-xs)', flexWrap: 'wrap' }}>
              {windowPresetOptions.slice(0, 3).map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => applyPreset(opt.value)}
                  disabled={viewMode === '3D'}
                  style={{
                    flex: 1,
                    padding: 'var(--space-sm)',
                    fontSize: '0.8rem',
                    background:
                      !useCustomWindow && windowPreset === opt.value
                        ? 'var(--accent-primary)'
                        : 'var(--bg-element)',
                    borderColor:
                      !useCustomWindow && windowPreset === opt.value
                        ? 'var(--accent-primary)'
                        : 'var(--border-subtle)',
                    color: !useCustomWindow && windowPreset === opt.value ? 'white' : 'var(--text-secondary)',
                    opacity: viewMode === '3D' ? 0.5 : 1,
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Manual Window/Level Controls */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-sm)',
              marginBottom: 'var(--space-sm)',
              marginTop: 'var(--space-sm)',
            }}
          >
            <SlidersHorizontal size={14} color="var(--text-muted)" />
            <span
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                textTransform: 'uppercase',
                color: 'var(--text-muted)',
                letterSpacing: '0.05em',
              }}
            >
              Manual Adjustment
            </span>
          </div>

          <ToggleSwitch
            label="Custom Window/Level"
            checked={useCustomWindow}
            onChange={setUseCustomWindow}
            disabled={viewMode === '3D'}
            description="Manually adjust HU range"
          />

          {useCustomWindow && (
            <>
              <RangeSlider
                label="Window Level (Center)"
                min={-1000}
                max={1000}
                step={10}
                value={customWindowLevel}
                valueDisplay={`${customWindowLevel} HU`}
                onChange={(e) => setCustomWindowLevel(parseInt(e.target.value))}
                disabled={viewMode === '3D'}
              />
              <RangeSlider
                label="Window Width (Range)"
                min={50}
                max={4000}
                step={50}
                value={customWindowWidth}
                valueDisplay={`${customWindowWidth} HU`}
                onChange={(e) => setCustomWindowWidth(parseInt(e.target.value))}
                disabled={viewMode === '3D'}
              />
              <div
                style={{
                  padding: 'var(--space-sm)',
                  background: 'var(--bg-element)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.7rem',
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                  marginTop: 'var(--space-xs)',
                }}
              >
                HU Range: {customWindowLevel - customWindowWidth / 2} to {customWindowLevel + customWindowWidth / 2}
              </div>
            </>
          )}

          <Divider spacing="sm" />

          <ToggleSwitch
            label="Segmentation Overlay"
            checked={showSegmentation}
            onChange={setShowSegmentation}
            disabled={viewMode === '3D'}
            description="Show segmented regions"
          />

          {showSegmentation && (
            <RangeSlider
              label="Overlay Opacity"
              min={0}
              max={1}
              step={0.1}
              value={segmentationOpacity}
              valueDisplay={Math.round(segmentationOpacity * 100) + '%'}
              onChange={(e) => setSegmentationOpacity(parseFloat(e.target.value))}
              disabled={viewMode === '3D'}
            />
          )}

          <Divider />

          {/* 3D Controls */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-sm)',
              marginBottom: 'var(--space-md)',
            }}
          >
            <Palette size={14} color="var(--text-muted)" />
            <span
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                textTransform: 'uppercase',
                color: 'var(--text-muted)',
                letterSpacing: '0.05em',
              }}
            >
              3D Rendering
            </span>
          </div>

          <ToggleSwitch
            label="Wireframe Mode"
            checked={showWireframe}
            onChange={setShowWireframe}
            disabled={viewMode === '2D'}
            description="Show mesh structure"
          />
        </div>
      </section>

      {/* Pipeline Status */}
      <section>
        <PipelineVisualizer steps={pipelineSteps} />
      </section>

      {/* Spacer */}
      <div style={{ flex: 1 }} />

      {/* Disclaimer */}
      <section
        style={{
          padding: 'var(--space-md)',
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.2)',
          borderRadius: 'var(--radius-md)',
        }}
      >
        <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'flex-start' }}>
          <Info size={16} color="var(--accent-error)" style={{ flexShrink: 0, marginTop: 2 }} />
          <p
            style={{
              fontSize: '0.75rem',
              color: 'var(--accent-error)',
              lineHeight: 1.5,
              margin: 0,
            }}
          >
            This system is for research and educational purposes only. Not intended for clinical
            diagnosis.
          </p>
        </div>
      </section>
    </div>
  );
}
