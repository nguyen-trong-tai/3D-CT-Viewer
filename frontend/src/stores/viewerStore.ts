/**
 * Viewer State Store (Zustand)
 *
 * Centralized state management replacing prop drilling from App.tsx.
 * All viewer-related state lives here — components consume directly.
 */

import { create } from 'zustand';
import {
  PIPELINE_STEPS,
  WINDOW_PRESETS,
  type CaseMetadata,
  type PipelineStep,
  type MeshVisibilityPreset,
  type SegmentationLabel,
  type SegmentationVisibility,
  type ViewMode,
  type WindowPresetKey,
} from '../types';

export type ToolMode = 'none' | 'zoom' | 'pan' | 'rotate' | 'crosshair';
type MprCrosshair = { x: number; y: number; z: number };

interface ViewerState {
  // App state
  appState: 'ENTRY' | 'VISUALIZATION';
  metadata: CaseMetadata | null;
  pipelineSteps: PipelineStep[];
  artifactRefreshVersion: number;

  // View settings
  viewMode: ViewMode;
  sliceIndex: number;
  activeTool: ToolMode;

  // Window/Level
  windowPreset: WindowPresetKey;
  useCustomWindow: boolean;
  customWindowLevel: number;
  customWindowWidth: number;

  // Overlays
  showSegmentation: boolean;
  segmentationOpacity: number;
  segmentationVisibility: SegmentationVisibility;
  segmentationLabels: SegmentationLabel[];
  meshVisibilityPreset: MeshVisibilityPreset;
  showWireframe: boolean;

  // MPR State
  mprCrosshair: MprCrosshair;
}

interface ViewerActions {
  // Navigation
  setAppState: (state: 'ENTRY' | 'VISUALIZATION') => void;
  setViewMode: (mode: ViewMode) => void;
  setSliceIndex: (index: number) => void;
  setActiveTool: (tool: ToolMode) => void;

  // Case lifecycle
  onUploadComplete: (meta: CaseMetadata) => void;
  updateMetadata: (updater: CaseMetadata | ((current: CaseMetadata | null) => CaseMetadata | null)) => void;
  resetCase: () => void;

  // Pipeline
  setPipelineSteps: (updater: PipelineStep[] | ((prev: PipelineStep[]) => PipelineStep[])) => void;
  bumpArtifactRefreshVersion: () => void;

  // Window/Level
  setWindowPreset: (preset: WindowPresetKey) => void;
  applyPreset: (preset: WindowPresetKey) => void;
  setUseCustomWindow: (use: boolean) => void;
  setCustomWindowLevel: (level: number) => void;
  setCustomWindowWidth: (width: number) => void;

  // Overlays
  setShowSegmentation: (show: boolean) => void;
  setSegmentationOpacity: (opacity: number) => void;
  setSegmentationVisibility: (
    updater: SegmentationVisibility | ((current: SegmentationVisibility) => SegmentationVisibility)
  ) => void;
  setSegmentationLabels: (labels: SegmentationLabel[]) => void;
  setMeshVisibilityPreset: (preset: MeshVisibilityPreset) => void;
  setShowWireframe: (show: boolean) => void;

  // MPR Actions
  setMprCrosshair: (crosshair: MprCrosshair | ((current: MprCrosshair) => MprCrosshair)) => void;
}

const initialState: ViewerState = {
  appState: 'ENTRY',
  metadata: null,
  pipelineSteps: PIPELINE_STEPS,
  artifactRefreshVersion: 0,
  viewMode: '2D',
  sliceIndex: 0,
  activeTool: 'none',
  windowPreset: 'SOFT_TISSUE',
  useCustomWindow: false,
  customWindowLevel: 40,
  customWindowWidth: 400,
  showSegmentation: false,
  segmentationOpacity: 0.5,
  segmentationVisibility: {},
  segmentationLabels: [],
  meshVisibilityPreset: 'default',
  showWireframe: false,
  mprCrosshair: { x: 0, y: 0, z: 0 },
};

export const useViewerStore = create<ViewerState & ViewerActions>((set) => ({
  ...initialState,

  setAppState: (appState) => set({ appState }),
  setViewMode: (viewMode) => set({ viewMode }),
  setSliceIndex: (sliceIndex) => set({ sliceIndex }),
  setActiveTool: (activeTool) => set({ activeTool }),

  onUploadComplete: (meta) =>
    set({
      metadata: meta,
      viewMode: '2D',
      sliceIndex: Math.floor(meta.totalSlices / 2),
      activeTool: 'none',
      appState: 'VISUALIZATION',
      pipelineSteps: PIPELINE_STEPS.map((step, index) => ({
        ...step,
        status:
          meta.status === 'ready'
            ? 'completed'
            : index === 0
              ? 'completed'
              : 'pending',
      })),
    }),

  updateMetadata: (updater) =>
    set((state) => ({
      metadata: typeof updater === 'function' ? updater(state.metadata) : updater,
    })),

  resetCase: () =>
    set({
      metadata: null,
      appState: 'ENTRY',
      pipelineSteps: PIPELINE_STEPS,
      artifactRefreshVersion: 0,
      viewMode: '2D',
      activeTool: 'none',
      sliceIndex: 0,
      showSegmentation: false,
      segmentationLabels: [],
      segmentationVisibility: {},
      meshVisibilityPreset: 'default',
      showWireframe: false,
    }),

  setPipelineSteps: (updater) =>
    set((state) => ({
      pipelineSteps: typeof updater === 'function' ? updater(state.pipelineSteps) : updater,
    })),

  bumpArtifactRefreshVersion: () =>
    set((state) => ({
      artifactRefreshVersion: state.artifactRefreshVersion + 1,
    })),

  applyPreset: (preset) => {
    const presetValues = WINDOW_PRESETS[preset];
    set({
      windowPreset: preset,
      useCustomWindow: false,
      customWindowLevel: presetValues.windowLevel,
      customWindowWidth: presetValues.windowWidth,
    });
  },

  setWindowPreset: (windowPreset) => set({ windowPreset }),
  setUseCustomWindow: (useCustomWindow) => set({ useCustomWindow }),
  setCustomWindowLevel: (customWindowLevel) => set({ customWindowLevel }),
  setCustomWindowWidth: (customWindowWidth) => set({ customWindowWidth }),
  setShowSegmentation: (showSegmentation) => set({ showSegmentation }),
  setSegmentationOpacity: (segmentationOpacity) => set({ segmentationOpacity }),
  setSegmentationVisibility: (segmentationVisibility) =>
    set((state) => ({
      segmentationVisibility:
        typeof segmentationVisibility === 'function'
          ? segmentationVisibility(state.segmentationVisibility)
          : segmentationVisibility,
    })),
  setSegmentationLabels: (segmentationLabels) =>
    set((state) => {
      const nextVisibility = { ...state.segmentationVisibility };
      for (const label of segmentationLabels) {
        if (label.key in nextVisibility) {
          continue;
        }
        nextVisibility[label.key] = label.available ? label.visible_by_default : false;
      }
      return {
        segmentationLabels,
        segmentationVisibility: nextVisibility,
      };
    }),
  setMeshVisibilityPreset: (meshVisibilityPreset) => set({ meshVisibilityPreset }),
  setShowWireframe: (showWireframe) => set({ showWireframe }),
  setMprCrosshair: (mprCrosshair) =>
    set((state) => ({
      mprCrosshair:
        typeof mprCrosshair === 'function'
          ? mprCrosshair(state.mprCrosshair)
          : mprCrosshair,
    })),
}));
