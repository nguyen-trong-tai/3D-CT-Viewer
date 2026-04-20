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
  type NoduleEntity,
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
  noduleEntities: NoduleEntity[];
  selectedNoduleId: string | null;
  focusedNoduleId: string | null;
  noduleFocusVersion: number;
  meshVisibilityPreset: MeshVisibilityPreset;
  showWireframe: boolean;

  // MPR State
  mprCrosshair: MprCrosshair;
  mprCrosshairCaseId: string | null;
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
  setNoduleEntities: (noduleEntities: NoduleEntity[]) => void;
  setSelectedNoduleId: (noduleId: string | null) => void;
  focusNodule: (noduleId: string) => void;
  clearNoduleSelection: () => void;
  setMeshVisibilityPreset: (preset: MeshVisibilityPreset) => void;
  setShowWireframe: (show: boolean) => void;

  // MPR Actions
  setMprCrosshair: (crosshair: MprCrosshair | ((current: MprCrosshair) => MprCrosshair)) => void;
  setMprCrosshairCaseId: (caseId: string | null) => void;
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
  noduleEntities: [],
  selectedNoduleId: null,
  focusedNoduleId: null,
  noduleFocusVersion: 0,
  meshVisibilityPreset: 'default',
  showWireframe: false,
  mprCrosshair: { x: 0, y: 0, z: 0 },
  mprCrosshairCaseId: null,
};

export const useViewerStore = create<ViewerState & ViewerActions>((set) => ({
  ...initialState,

  setAppState: (appState) => set({ appState }),
  setViewMode: (viewMode) =>
    set((state) => ({
      viewMode,
      sliceIndex: viewMode === '2D' ? state.mprCrosshair.z : state.sliceIndex,
      activeTool:
        viewMode === 'MPR' || viewMode === 'MPR_3D' || state.activeTool !== 'crosshair'
          ? state.activeTool
          : 'none',
    })),
  setSliceIndex: (sliceIndex) => set({ sliceIndex }),
  setActiveTool: (activeTool) => set({ activeTool }),

  onUploadComplete: (meta) =>
    set({
      metadata: meta,
      viewMode: '2D',
      sliceIndex: Math.floor(meta.totalSlices / 2),
      activeTool: 'none',
      appState: 'VISUALIZATION',
      segmentationLabels: [],
      noduleEntities: [],
      selectedNoduleId: null,
      focusedNoduleId: null,
      noduleFocusVersion: 0,
      segmentationVisibility: {},
      meshVisibilityPreset: 'default',
      mprCrosshair: { x: 0, y: 0, z: 0 },
      mprCrosshairCaseId: null,
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
      noduleEntities: [],
      selectedNoduleId: null,
      focusedNoduleId: null,
      noduleFocusVersion: 0,
      segmentationVisibility: {},
      meshVisibilityPreset: 'default',
      showWireframe: false,
      mprCrosshair: { x: 0, y: 0, z: 0 },
      mprCrosshairCaseId: null,
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
  setNoduleEntities: (noduleEntities) =>
    set((state) => {
      const nextSelectedId =
        state.selectedNoduleId && noduleEntities.some((nodule) => nodule.id === state.selectedNoduleId)
          ? state.selectedNoduleId
          : null;
      const nextFocusedId =
        state.focusedNoduleId && noduleEntities.some((nodule) => nodule.id === state.focusedNoduleId)
          ? state.focusedNoduleId
          : null;

      return {
        noduleEntities,
        selectedNoduleId: nextSelectedId,
        focusedNoduleId: nextFocusedId,
      };
    }),
  setSelectedNoduleId: (selectedNoduleId) => set({ selectedNoduleId }),
  focusNodule: (noduleId) =>
    set((state) => {
      const isSameNodule =
        state.selectedNoduleId === noduleId && state.focusedNoduleId === noduleId;

      if (isSameNodule) {
        return {
          selectedNoduleId: null,
          focusedNoduleId: null,
        };
      }

      return {
        selectedNoduleId: noduleId,
        focusedNoduleId: noduleId,
        noduleFocusVersion: state.noduleFocusVersion + 1,
      };
    }),
  clearNoduleSelection: () =>
    set({
      selectedNoduleId: null,
      focusedNoduleId: null,
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
  setMprCrosshairCaseId: (mprCrosshairCaseId) => set({ mprCrosshairCaseId }),
}));
