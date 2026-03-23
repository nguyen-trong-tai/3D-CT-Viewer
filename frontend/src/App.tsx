import { useEffect, useState } from 'react';
import { MainLayout } from './components/Layout/MainLayout';
import { SliceViewer } from './components/CTViewer/SliceViewer';
import { ModelViewer } from './components/MeshViewer/ModelViewer';
import VTKHybridViewer from './components/CTViewer/VTKHybridViewer';
import { UploadPage } from './components/Entry/UploadPage';
import { useViewerStore } from './stores/viewerStore';
import { casesApi } from './services/api';

function App() {
  const appState = useViewerStore(s => s.appState);
  const metadata = useViewerStore(s => s.metadata);
  const viewMode = useViewerStore(s => s.viewMode);
  const sliceIndex = useViewerStore(s => s.sliceIndex);
  const setSliceIndex = useViewerStore(s => s.setSliceIndex);
  const windowPreset = useViewerStore(s => s.windowPreset);
  const showSegmentation = useViewerStore(s => s.showSegmentation);
  const segmentationOpacity = useViewerStore(s => s.segmentationOpacity);
  const useCustomWindow = useViewerStore(s => s.useCustomWindow);
  const customWindowLevel = useViewerStore(s => s.customWindowLevel);
  const customWindowWidth = useViewerStore(s => s.customWindowWidth);
  const showWireframe = useViewerStore(s => s.showWireframe);
  const onUploadComplete = useViewerStore(s => s.onUploadComplete);
  const setPipelineSteps = useViewerStore(s => s.setPipelineSteps);
  const [showVTK, setShowVTK] = useState(false);

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
          showVTK ? (
            <div style={{ width: '100%', height: '100%', position: 'relative' }}>
              <button 
                onClick={() => setShowVTK(false)}
                style={{ position: 'absolute', top: 10, right: 10, zIndex: 100, padding: '5px 10px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
              >
                Back to Three.js
              </button>
              <VTKHybridViewer caseId={metadata.id} />
            </div>
          ) : (
            <div style={{ width: '100%', height: '100%', position: 'relative' }}>
              <button 
                onClick={() => setShowVTK(true)}
                style={{ position: 'absolute', top: 10, right: 10, zIndex: 100, padding: '5px 10px', background: '#eab308', color: 'black', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
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
        ) : null
      }
    />
  );
}

export default App;
