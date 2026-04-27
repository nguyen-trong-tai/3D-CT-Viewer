import type { MPRView } from '../types';

export interface SliceRenderOptions {
    includeBadges?: boolean;
    sliceIndex?: number;
}

export interface SliceVideoExportOptions {
    fps: number;
    startSlice: number;
    endSlice: number;
    includeBadges?: boolean;
}

export interface SliceExporter {
    renderFrame: (options?: SliceRenderOptions) => Promise<HTMLCanvasElement>;
    capturePng: (options?: SliceRenderOptions) => Promise<Blob>;
    captureVideo?: (options: SliceVideoExportOptions) => Promise<Blob>;
    getSliceRange: () => { min: number; max: number; current: number };
}

export interface ModelExporter {
    renderFrame: () => Promise<HTMLCanvasElement>;
    capturePng: () => Promise<Blob>;
}

const sliceExporters = new Map<MPRView, SliceExporter>();
let modelExporter: ModelExporter | null = null;

const notifyExportersUpdated = () => {
    if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event('viewer-exporters-updated'));
    }
};

export const registerSliceExporter = (view: MPRView, exporter: SliceExporter) => {
    sliceExporters.set(view, exporter);
    notifyExportersUpdated();

    return () => {
        if (sliceExporters.get(view) === exporter) {
            sliceExporters.delete(view);
            notifyExportersUpdated();
        }
    };
};

export const getSliceExporter = (view: MPRView): SliceExporter | null =>
    sliceExporters.get(view) ?? null;

export const registerModelExporter = (exporter: ModelExporter) => {
    modelExporter = exporter;
    notifyExportersUpdated();

    return () => {
        if (modelExporter === exporter) {
            modelExporter = null;
            notifyExportersUpdated();
        }
    };
};

export const getModelExporter = (): ModelExporter | null => modelExporter;
