import { useCallback, useEffect, useRef, useState } from 'react';
import { Box, Loader2 } from 'lucide-react';
import { MainLayout } from './components/Layout/MainLayout';
import { SliceViewer } from './components/CTViewer/SliceViewer';
import { ModelViewer } from './components/MeshViewer/ModelViewer';
import VTKHybridViewer from './components/CTViewer/VTKHybridViewer';
import { UploadPage } from './components/Entry/UploadPage';
import { PipelineVisualizer } from './components/Pipeline/PipelineVisualizer';
import { useViewerStore } from './stores/viewerStore';
import { casesApi, ctApi, maskApi } from './services/api';
import type {
  CaseEventPayload,
  PipelineSnapshot,
  PipelineStageSnapshot,
  PipelineStatus,
} from './services/api';
import type { CaseStatus, PipelineStepStatus } from './types';

const PIPELINE_POLL_INTERVAL_MS = 5000;

const ARTIFACT_BY_STAGE: Record<string, string> = {
  load_volume: 'ct_volume',
  segmentation: 'segmentation_mask',
  sdf: 'sdf',
  mesh: 'mesh',
};

const mapBackendStageStatus = (status?: string): PipelineStepStatus => {
  if (status === 'completed' || status === 'skipped') {
    return 'completed';
  }
  if (status === 'running') {
    return 'running';
  }
  if (status === 'failed') {
    return 'failed';
  }
  return 'pending';
};

const normalizeCaseStatus = (status?: string): CaseStatus => {
  switch (status) {
    case 'uploading':
    case 'uploaded':
    case 'processing':
    case 'ready':
    case 'error':
      return status;
    default:
      return 'pending';
  }
};

const MeshPendingView: React.FC<{
  pipelineLabel: string;
  currentStageLabel: string;
  showSpinner: boolean;
}> = ({ pipelineLabel, currentStageLabel, showSpinner }) => {
  const pipelineSteps = useViewerStore((state) => state.pipelineSteps);

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(180deg, #0f1115 0%, #0a0c10 100%)',
        padding: 'var(--space-xl)',
      }}
    >
      <div
        style={{
          width: 'min(420px, 100%)',
          padding: 'var(--space-xl)',
          borderRadius: 'var(--radius-xl)',
          border: '1px solid var(--border-subtle)',
          background: 'rgba(8, 14, 24, 0.88)',
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-sm)',
            marginBottom: 'var(--space-md)',
            color: 'var(--text-primary)',
          }}
        >
          {showSpinner ? (
            <Loader2 size={18} color="var(--accent-primary)" style={{ animation: 'spin 1s linear infinite' }} />
          ) : (
            <Box size={18} color="var(--accent-primary)" />
          )}
          <strong>3D Viewer Pending</strong>
        </div>

        <p style={{ marginTop: 0, marginBottom: 'var(--space-sm)', color: 'var(--text-secondary)' }}>
          2D view is ready. The remaining pipeline is still running in the background.
        </p>
        <p style={{ marginTop: 0, marginBottom: 'var(--space-lg)', color: 'var(--text-muted)', fontSize: '0.9rem' }}>
          {pipelineLabel}
          {currentStageLabel ? ` ${currentStageLabel}` : ''}
        </p>

        <PipelineVisualizer steps={pipelineSteps} compact />
      </div>
    </div>
  );
};

function App() {
  const appState = useViewerStore((state) => state.appState);
  const metadata = useViewerStore((state) => state.metadata);
  const pipelineSteps = useViewerStore((state) => state.pipelineSteps);
  const viewMode = useViewerStore((state) => state.viewMode);
  const sliceIndex = useViewerStore((state) => state.sliceIndex);
  const setSliceIndex = useViewerStore((state) => state.setSliceIndex);
  const windowPreset = useViewerStore((state) => state.windowPreset);
  const showSegmentation = useViewerStore((state) => state.showSegmentation);
  const setShowSegmentation = useViewerStore((state) => state.setShowSegmentation);
  const segmentationOpacity = useViewerStore((state) => state.segmentationOpacity);
  const useCustomWindow = useViewerStore((state) => state.useCustomWindow);
  const customWindowLevel = useViewerStore((state) => state.customWindowLevel);
  const customWindowWidth = useViewerStore((state) => state.customWindowWidth);
  const showWireframe = useViewerStore((state) => state.showWireframe);
  const onUploadComplete = useViewerStore((state) => state.onUploadComplete);
  const updateMetadata = useViewerStore((state) => state.updateMetadata);
  const setPipelineSteps = useViewerStore((state) => state.setPipelineSteps);
  const setSegmentationLabels = useViewerStore((state) => state.setSegmentationLabels);
  const bumpArtifactRefreshVersion = useViewerStore((state) => state.bumpArtifactRefreshVersion);

  const [showVTK, setShowVTK] = useState(false);
  const [meshAvailable, setMeshAvailable] = useState(false);

  const requestedProcessingRef = useRef<Set<string>>(new Set());
  const autoEnabledSegmentationRef = useRef<Set<string>>(new Set());
  const artifactAvailabilityRef = useRef<
    Map<string, { ctVolume: boolean; ctPreview: boolean }>
  >(new Map());

  const syncSegmentationPresentation = useCallback(
    async (caseId: string, autoEnable: boolean) => {
      const manifest = await maskApi.getSegmentationManifest(caseId);
      if (useViewerStore.getState().metadata?.id !== caseId) {
        return;
      }
      const labels = manifest?.labels ?? [];

      setSegmentationLabels(labels);
      ctApi.invalidateMetadata(caseId);
      bumpArtifactRefreshVersion();

      if (
        autoEnable &&
        !autoEnabledSegmentationRef.current.has(caseId) &&
        labels.some((label) => label.available && label.render_2d)
      ) {
        setShowSegmentation(true);
        autoEnabledSegmentationRef.current.add(caseId);
      }
    },
    [bumpArtifactRefreshVersion, setSegmentationLabels, setShowSegmentation]
  );

  const applyPipelineSnapshot = useCallback(
    (caseId: string, snapshot: PipelineSnapshot | Pick<PipelineStatus, 'overall_status' | 'stages' | 'artifacts'>, autoEnableSegmentation: boolean) => {
      const stagesByName = new Map<string, PipelineStageSnapshot>(
        (snapshot.stages ?? []).map((stage) => [stage.name, stage])
      );
      const nextCtVolume = Boolean(snapshot.artifacts?.ct_volume);
      const nextCtPreview = Boolean(snapshot.artifacts?.ct_volume_preview);
      const previousArtifacts = artifactAvailabilityRef.current.get(caseId) ?? {
        ctVolume: false,
        ctPreview: false,
      };

      if (nextCtVolume && !previousArtifacts.ctVolume) {
        ctApi.invalidateMetadata(caseId);
        bumpArtifactRefreshVersion();
      }

      artifactAvailabilityRef.current.set(caseId, {
        ctVolume: nextCtVolume,
        ctPreview: nextCtPreview,
      });

      setPipelineSteps((prev) =>
        prev.map((step) => {
          const backendStage = stagesByName.get(step.id);
          const artifactName = ARTIFACT_BY_STAGE[step.id];
          const hasArtifact = artifactName ? Boolean(snapshot.artifacts?.[artifactName]) : false;
          const loadVolumeReady = Boolean(snapshot.artifacts?.ct_volume);
          const previewReady = Boolean(snapshot.artifacts?.ct_volume_preview);
          const effectiveBackendStatus =
            step.id === 'load_volume'
              ? loadVolumeReady
                ? 'completed'
                : snapshot.overall_status === 'error'
                  ? 'failed'
                  : previewReady || snapshot.overall_status === 'uploading'
                    ? 'running'
                    : backendStage?.status
              : backendStage?.status;
          const fallbackStatus =
            step.id === 'load_volume'
              ? loadVolumeReady
                ? 'completed'
                : snapshot.overall_status === 'error'
                  ? 'failed'
                  : previewReady || snapshot.overall_status === 'uploading'
                    ? 'running'
                    : 'pending'
              : hasArtifact
                ? 'completed'
                : 'pending';

          return {
            ...step,
            status: mapBackendStageStatus(effectiveBackendStatus ?? fallbackStatus),
            duration:
              backendStage?.duration_seconds != null
                ? backendStage.duration_seconds * 1000
                : step.duration,
          };
        })
      );

      setMeshAvailable(Boolean(snapshot.artifacts?.mesh));
      updateMetadata((current) =>
        current && current.id === caseId
          ? { ...current, status: normalizeCaseStatus(snapshot.overall_status) }
          : current
      );

      if (snapshot.artifacts?.segmentation_mask || snapshot.artifacts?.segmentation_manifest) {
        void syncSegmentationPresentation(caseId, autoEnableSegmentation);
      }
    },
    [bumpArtifactRefreshVersion, setPipelineSteps, syncSegmentationPresentation, updateMetadata]
  );

  useEffect(() => {
    if (appState !== 'VISUALIZATION' || !metadata?.id) {
      setMeshAvailable(false);
      return;
    }

    const caseId = metadata.id;
    const autoEnableSegmentation = metadata.status !== 'ready';
    let cancelled = false;

    setMeshAvailable(false);
    setShowVTK(false);

    const syncPipelineState = async (allowStartProcessing: boolean) => {
      const status = await casesApi.getPipelineStatus(caseId);
      if (cancelled) {
        return;
      }

      applyPipelineSnapshot(caseId, status, autoEnableSegmentation);

      if (
        allowStartProcessing &&
        status.overall_status === 'uploaded' &&
        !requestedProcessingRef.current.has(caseId)
      ) {
        requestedProcessingRef.current.add(caseId);
        try {
          await casesApi.processCase(caseId);
          if (!cancelled) {
            updateMetadata((current) =>
              current && current.id === caseId ? { ...current, status: 'processing' } : current
            );
          }
        } catch {
          requestedProcessingRef.current.delete(caseId);
        }
      }
    };

    void syncPipelineState(true);

    const unsubscribe = casesApi.subscribeToCaseEvents(caseId, {
      onEvent: (payload: CaseEventPayload) => {
        if (cancelled || payload.case_id !== caseId) {
          return;
        }

        if (payload.snapshot) {
          applyPipelineSnapshot(caseId, payload.snapshot, autoEnableSegmentation);
        }

        if (
          payload.artifact === 'segmentation_mask' ||
          payload.artifact === 'segmentation_manifest'
        ) {
          void syncSegmentationPresentation(caseId, autoEnableSegmentation);
        }
      },
    });

    const pollInterval = window.setInterval(() => {
      void syncPipelineState(false);
    }, PIPELINE_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      unsubscribe();
      window.clearInterval(pollInterval);
    };
  }, [
    appState,
    applyPipelineSnapshot,
    metadata?.id,
    metadata?.status,
    syncSegmentationPresentation,
    updateMetadata,
  ]);

  useEffect(() => {
    if (appState === 'ENTRY') {
      artifactAvailabilityRef.current.clear();
    }
  }, [appState]);

  if (appState === 'ENTRY') {
    return <UploadPage onUploadComplete={onUploadComplete} />;
  }

  const runningStep = pipelineSteps.find((step) => step.status === 'running');
  const hasBackgroundWork =
    metadata?.status === 'uploading' ||
    metadata?.status === 'uploaded' ||
    metadata?.status === 'processing';
  const pipelineLabel =
    metadata?.status === 'ready'
      ? 'All processing artifacts are available.'
      : metadata?.status === 'uploading'
        ? '2D preview is ready while the full-resolution volume finishes saving.'
      : hasBackgroundWork
        ? 'Pipeline updates will appear here as each stage finishes.'
        : 'Preparing background pipeline state...';
  const currentStageLabel = runningStep ? `Current stage: ${runningStep.label}.` : '';

  return (
    <MainLayout
      viewMode={viewMode}
      viewer2D={
        metadata ? (
          <SliceViewer
            caseId={metadata.id}
            totalSlices={metadata.totalSlices}
            currentIndex={sliceIndex}
            onIndexChange={setSliceIndex}
            showControls={true}
            viewLabel="Axial CT"
            windowPreset={windowPreset}
            showSegmentation={showSegmentation}
            segmentationOpacity={segmentationOpacity}
            useCustomWindow={useCustomWindow}
            customWindowLevel={customWindowLevel}
            customWindowWidth={customWindowWidth}
          />
        ) : (
          <div
            style={{
              width: '100%',
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-muted)',
            }}
          >
            Initializing viewer...
          </div>
        )
      }
      viewer2D_coronal={
        metadata ? (
          <SliceViewer
            caseId={metadata.id}
            totalSlices={metadata.totalSlices}
            showControls={true}
            viewLabel="Coronal MPR"
            viewType="CORONAL"
            windowPreset={windowPreset}
            showSegmentation={showSegmentation}
            segmentationOpacity={segmentationOpacity}
            useCustomWindow={useCustomWindow}
            customWindowLevel={customWindowLevel}
            customWindowWidth={customWindowWidth}
          />
        ) : undefined
      }
      viewer2D_sagittal={
        metadata ? (
          <SliceViewer
            caseId={metadata.id}
            totalSlices={metadata.totalSlices}
            showControls={true}
            viewLabel="Sagittal MPR"
            viewType="SAGITTAL"
            windowPreset={windowPreset}
            showSegmentation={showSegmentation}
            segmentationOpacity={segmentationOpacity}
            useCustomWindow={useCustomWindow}
            customWindowLevel={customWindowLevel}
            customWindowWidth={customWindowWidth}
          />
        ) : undefined
      }
      viewer3D={
        metadata ? (
          meshAvailable ? (
            showVTK ? (
              <div style={{ width: '100%', height: '100%', position: 'relative' }}>
                <button
                  onClick={() => setShowVTK(false)}
                  style={{
                    position: 'absolute',
                    top: 10,
                    right: 10,
                    zIndex: 100,
                    padding: '5px 10px',
                    background: '#3b82f6',
                    color: 'white',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                  }}
                >
                  Back to Three.js
                </button>
                <VTKHybridViewer caseId={metadata.id} />
              </div>
            ) : (
              <div style={{ width: '100%', height: '100%', position: 'relative' }}>
                <button
                  onClick={() => setShowVTK(true)}
                  style={{
                    position: 'absolute',
                    top: 10,
                    right: 10,
                    zIndex: 100,
                    padding: '5px 10px',
                    background: '#eab308',
                    color: 'black',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                  }}
                >
                  Try VTK.js PoC
                </button>
                <ModelViewer
                  caseId={metadata.id}
                  currentSliceIndex={sliceIndex}
                  voxelSpacing={metadata.voxelSpacing}
                  showWireframe={showWireframe}
                  totalSlices={metadata.totalSlices}
                  showSliceIndicator={false}
                />
              </div>
            )
          ) : (
            <MeshPendingView
              pipelineLabel={pipelineLabel}
              currentStageLabel={currentStageLabel}
              showSpinner={hasBackgroundWork}
            />
          )
        ) : null
      }
    />
  );
}

export default App;
