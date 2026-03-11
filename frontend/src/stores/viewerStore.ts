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
  type ViewMode,
  type WindowPresetKey,
} from '../types';

interface ViewerState {
  // App state
  appState: 'ENTRY' | 'VISUALIZATION';
  metadata: CaseMetadata | null;
  pipelineSteps: PipelineStep[];

  // View settings
  viewMode: ViewMode;
  sliceIndex: number;

  // Window/Level
  windowPreset: WindowPresetKey;
  useCustomWindow: boolean;
  customWindowLevel: number;
  customWindowWidth: number;

  // Overlays
  showSegmentation: boolean;
  segmentationOpacity: number;
  showWireframe: boolean;
}

interface ViewerActions {
  // Navigation
  setAppState: (state: 'ENTRY' | 'VISUALIZATION') => void;
  setViewMode: (mode: ViewMode) => void;
  setSliceIndex: (index: number) => void;

  // Case lifecycle
  onUploadComplete: (meta: CaseMetadata) => void;
  resetCase: () => void;

  // Pipeline
  setPipelineSteps: (updater: PipelineStep[] | ((prev: PipelineStep[]) => PipelineStep[])) => void;

  // Window/Level
  setWindowPreset: (preset: WindowPresetKey) => void;
  applyPreset: (preset: WindowPresetKey) => void;
  setUseCustomWindow: (use: boolean) => void;
  setCustomWindowLevel: (level: number) => void;
  setCustomWindowWidth: (width: number) => void;

  // Overlays
  setShowSegmentation: (show: boolean) => void;
  setSegmentationOpacity: (opacity: number) => void;
  setShowWireframe: (show: boolean) => void;
}

const initialState: ViewerState = {
  appState: 'ENTRY',
  metadata: null,
  pipelineSteps: PIPELINE_STEPS,
  viewMode: '2D',
  sliceIndex: 0,
  windowPreset: 'SOFT_TISSUE',
  useCustomWindow: false,
  customWindowLevel: 40,
  customWindowWidth: 400,
  showSegmentation: false,
  segmentationOpacity: 0.5,
  showWireframe: false,
};

export const useViewerStore = create<ViewerState & ViewerActions>((set) => ({
  ...initialState,

  setAppState: (appState) => set({ appState }),
  setViewMode: (viewMode) => set({ viewMode }),
  setSliceIndex: (sliceIndex) => set({ sliceIndex }),

  onUploadComplete: (meta) =>
    set({
      metadata: meta,
      sliceIndex: Math.floor(meta.totalSlices / 2),
      appState: 'VISUALIZATION',
      pipelineSteps: PIPELINE_STEPS.map((s) => ({ ...s, status: 'completed' as const })),
    }),

  resetCase: () =>
    set({
      metadata: null,
      appState: 'ENTRY',
      pipelineSteps: PIPELINE_STEPS,
    }),

  setPipelineSteps: (updater) =>
    set((state) => ({
      pipelineSteps: typeof updater === 'function' ? updater(state.pipelineSteps) : updater,
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
  setShowWireframe: (showWireframe) => set({ showWireframe }),
}));
