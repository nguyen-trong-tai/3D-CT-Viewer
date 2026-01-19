import { useState } from 'react';
import { MainLayout } from './components/Layout/MainLayout';
import { SliceViewer } from './components/CTViewer/SliceViewer';
import { ModelViewer } from './components/MeshViewer/ModelViewer';
import { PipelineVisualizer } from './components/Pipeline/PipelineVisualizer';
import { RangeSlider, ToggleSwitch, IconButton } from './components/UI/Controls';
import { ViewModeSelector, type ViewMode } from './components/UI/ViewModeSelector';
import { UploadPage } from './components/Entry/UploadPage';
import { PIPELINE_STEPS } from './types';
import type { CaseMetadata, PipelineStep } from './types';
import { FileText, Settings, Info, LogOut } from 'lucide-react';

function App() {
  // Application Flow State
  const [appState, setAppState] = useState<'ENTRY' | 'VISUALIZATION'>('ENTRY');

  // Global Data State
  const [metadata, setMetadata] = useState<CaseMetadata | null>(null);
  const [pipelineSteps, setPipelineSteps] = useState<PipelineStep[]>(PIPELINE_STEPS);

  // Viewer State
  const [viewMode, setViewMode] = useState<ViewMode>('LINKED');
  const [sliceIndex, setSliceIndex] = useState(0);
  const [showSegmentation, setShowSegmentation] = useState(true);
  const [segmentationOpacity, setSegmentationOpacity] = useState(0.5);
  const [windowPreset, setWindowPreset] = useState<'LUNG' | 'SOFT_TISSUE'>('SOFT_TISSUE');

  // 3D State
  const [showWireframe, setShowWireframe] = useState(false);

  // Update pipeline occasionally for demo effect (simulated)

  const handleUploadComplete = (meta: CaseMetadata) => {
    setMetadata(meta);
    setSliceIndex(Math.floor(meta.totalSlices / 2));
    setAppState('VISUALIZATION');

    // Mark all steps as completed since we waited for processing in UploadPage
    setPipelineSteps(PIPELINE_STEPS.map(s => ({ ...s, status: 'completed' })));
  };

  const handleReset = () => {
    if (confirm("Are you sure you want to load a new case? Current progress will be lost.")) {
      setMetadata(null);
      setAppState('ENTRY');
    }
  };

  const sidebarContent = (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>

      {/* Case Management */}
      <div>
        <h3 style={{ marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <FileText size={18} color="var(--accent-primary)" />
          Case Info
        </h3>
        <div className="card" style={{ fontSize: '0.85rem' }}>
          {metadata ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
              <span style={{ color: 'var(--text-scnd)' }}>ID:</span>
              <span style={{ textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{metadata.id}</span>
              <span style={{ color: 'var(--text-scnd)' }}>Slices:</span>
              <span style={{ textAlign: 'right' }}>{metadata.totalSlices}</span>
              <span style={{ color: 'var(--text-scnd)' }}>Dims:</span>
              <span style={{ textAlign: 'right' }}>{metadata.dimensions.join('x')}</span>
              <span style={{ color: 'var(--text-scnd)' }}>Spacing:</span>
              <span style={{ textAlign: 'right' }}>{metadata.voxelSpacing.map(v => v.toFixed(1)).join(', ')}</span>
            </div>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>No active case</div>
          )}

          <div style={{ borderTop: '1px solid var(--border-subtle)', marginTop: '16px', paddingTop: '16px' }}>
            <button className="secondary" style={{ width: '100%', fontSize: '0.85rem' }} onClick={handleReset}>
              <LogOut size={14} style={{ marginRight: '8px' }} />
              Load New Case
            </button>
          </div>
        </div>
      </div>

      {/* View Settings */}
      <div>
        <h3 style={{ marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Settings size={18} color="var(--accent-primary)" />
          View Settings
        </h3>

        <ViewModeSelector mode={viewMode} onChange={setViewMode} />

        <div className="card">
          <h4 style={{ fontSize: '0.8rem', marginBottom: '12px', color: 'var(--text-scnd)' }}>CT Visualization</h4>

          <div style={{ marginBottom: '16px', display: 'flex', gap: '8px' }}>
            <IconButton
              active={windowPreset === 'SOFT_TISSUE'}
              onClick={() => setWindowPreset('SOFT_TISSUE')}
              style={{ flex: 1, fontSize: '0.8rem' }}
              disabled={viewMode === '3D'}
            >
              Soft Tissue
            </IconButton>
            <IconButton
              active={windowPreset === 'LUNG'}
              onClick={() => setWindowPreset('LUNG')}
              style={{ flex: 1, fontSize: '0.8rem' }}
              disabled={viewMode === '3D'}
            >
              Lung
            </IconButton>
          </div>

          <ToggleSwitch
            label="Show Segmentation"
            checked={showSegmentation}
            onChange={setShowSegmentation}
            disabled={viewMode === '3D'} // Example constraint
          />
          {showSegmentation && (
            <RangeSlider
              label="Opacity"
              min={0} max={1} step={0.1}
              value={segmentationOpacity}
              onChange={(e) => setSegmentationOpacity(parseFloat(e.target.value))}
              disabled={viewMode === '3D'}
            />
          )}

          <div style={{ height: '1px', background: 'var(--border-subtle)', margin: '16px 0' }} />

          <h4 style={{ fontSize: '0.8rem', marginBottom: '12px', color: 'var(--text-scnd)' }}>3D Rendering</h4>
          <ToggleSwitch
            label="Wireframe Mesh"
            checked={showWireframe}
            onChange={setShowWireframe}
            disabled={viewMode === '2D'}
          />
        </div>
      </div>

      {/* Pipeline Status */}
      <PipelineVisualizer steps={pipelineSteps} />

      {/* Disclaimer */}
      <div style={{ marginTop: 'auto', padding: '12px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: '8px', display: 'flex', gap: '12px' }}>
        <Info color="var(--accent-error)" size={20} style={{ flexShrink: 0 }} />
        <small style={{ color: 'var(--accent-error)', lineHeight: 1.4 }}>
          This system is for research and educational demonstration only. It is not intended for clinical diagnosis.
        </small>
      </div>
    </div>
  );

  if (appState === 'ENTRY') {
    return <UploadPage onUploadComplete={handleUploadComplete} />;
  }

  return (
    <MainLayout
      viewMode={viewMode}
      sidebar={sidebarContent}
      viewer2D={
        metadata ? (
          <SliceViewer
            caseId={metadata.id}
            totalSlices={metadata.totalSlices}
            currentIndex={sliceIndex}
            onIndexChange={setSliceIndex}
            showSegmentation={showSegmentation}
            segmentationOpacity={segmentationOpacity}
            windowPreset={windowPreset}
          />
        ) : (
          <div className="flex-center full-size">Initializing...</div>
        )
      }
      viewer3D={
        metadata ? (
          <ModelViewer
            caseId={metadata.id}
            currentSliceIndex={sliceIndex}
            voxelSpacing={metadata.voxelSpacing}
            showWireframe={showWireframe}
            totalSlices={metadata.totalSlices}
          />
        ) : null
      }
    />
  );
}

export default App;
