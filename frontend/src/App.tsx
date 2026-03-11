import { useEffect } from 'react';
import { MainLayout } from './components/Layout/MainLayout';
import { Sidebar } from './components/Layout/Sidebar';
import { SliceViewer } from './components/CTViewer/SliceViewer';
import { ModelViewer } from './components/MeshViewer/ModelViewer';
import { UploadPage } from './components/Entry/UploadPage';
import { useViewerStore } from './stores/viewerStore';
import { casesApi } from './services/api';

function App() {
  const {
    appState,
    metadata,
    viewMode,
    sliceIndex,
    setSliceIndex,
    windowPreset,
    showSegmentation,
    segmentationOpacity,
    useCustomWindow,
    customWindowLevel,
    customWindowWidth,
    showWireframe,
    onUploadComplete,
    setPipelineSteps,
  } = useViewerStore();

  // Fetch pipeline status when in visualization mode
  useEffect(() => {
    if (appState === 'VISUALIZATION' && metadata?.id) {
      const fetchPipeline = async () => {
        try {
          const status = await casesApi.getPipelineStatus(metadata.id);
          if (status.stages) {
            setPipelineSteps((prev) =>
              prev.map((step) => {
                const backendStage = status.stages.find((s) => s.name === step.id);
                if (backendStage) {
                  return {
                    ...step,
                    status:
                      backendStage.status === 'completed'
                        ? 'completed'
                        : backendStage.status === 'running'
                          ? 'running'
                          : backendStage.status === 'failed'
                            ? 'failed'
                            : 'pending',
                  };
                }
                return step;
              }),
            );
          }
        } catch {
          setPipelineSteps((prev) => prev.map((s) => ({ ...s, status: 'completed' as const })));
        }
      };
      fetchPipeline();
    }
  }, [appState, metadata?.id, setPipelineSteps]);

  if (appState === 'ENTRY') {
    return <UploadPage onUploadComplete={onUploadComplete} />;
  }

  return (
    <MainLayout
      viewMode={viewMode}
      sidebar={<Sidebar />}
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
      viewer3D={
        metadata ? (
          <ModelViewer
            caseId={metadata.id}
            currentSliceIndex={sliceIndex}
            voxelSpacing={metadata.voxelSpacing}
            showWireframe={showWireframe}
            totalSlices={metadata.totalSlices}
            showSliceIndicator={false}
          />
        ) : null
      }
    />
  );
}

export default App;
