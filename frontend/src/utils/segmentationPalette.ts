import type {
    SegmentationLabel,
    SegmentationPaletteMode,
} from '../types';

const CLINICAL_LABEL_COLORS: Record<string, string> = {
    left_lung: '#9bc2d3',
    right_lung: '#78afc4',
    lung: '#86b8ca',
    nodule: '#d97706',
};

const COLOR_SAFE_LABEL_COLORS: Record<string, string> = {
    left_lung: '#4e79a7',
    right_lung: '#76b7b2',
    lung: '#5f9fb0',
    nodule: '#f28e2b',
};

export interface SegmentationPaletteTokens {
    lungLeft: string;
    lungRight: string;
    lung: string;
    nodule: string;
    noduleHover: string;
    noduleSelected: string;
    noduleOutline: string;
    noduleSelectedText: string;
    noduleChipBackground: string;
    noduleChipText: string;
    crosshair: string;
    sliderMarker: string;
    sliderMarkerActive: string;
}

const PALETTE_TOKENS: Record<SegmentationPaletteMode, SegmentationPaletteTokens> = {
    clinical: {
        lungLeft: CLINICAL_LABEL_COLORS.left_lung,
        lungRight: CLINICAL_LABEL_COLORS.right_lung,
        lung: CLINICAL_LABEL_COLORS.lung,
        nodule: CLINICAL_LABEL_COLORS.nodule,
        noduleHover: '#f59e0b',
        noduleSelected: '#fde047',
        noduleOutline: '#fff3bf',
        noduleSelectedText: '#fff7db',
        noduleChipBackground: 'rgba(217, 119, 6, 0.16)',
        noduleChipText: '#fdba74',
        crosshair: '#38bdf8',
        sliderMarker: 'rgba(155, 194, 211, 0.62)',
        sliderMarkerActive: '#fde047',
    },
    color_safe: {
        lungLeft: COLOR_SAFE_LABEL_COLORS.left_lung,
        lungRight: COLOR_SAFE_LABEL_COLORS.right_lung,
        lung: COLOR_SAFE_LABEL_COLORS.lung,
        nodule: COLOR_SAFE_LABEL_COLORS.nodule,
        noduleHover: '#ffb55a',
        noduleSelected: '#facc15',
        noduleOutline: '#fff2a8',
        noduleSelectedText: '#fff8d6',
        noduleChipBackground: 'rgba(242, 142, 43, 0.16)',
        noduleChipText: '#ffd08a',
        crosshair: '#67e8f9',
        sliderMarker: 'rgba(118, 183, 178, 0.7)',
        sliderMarkerActive: '#facc15',
    },
};

const SEGMENTATION_LABEL_COLORS: Record<SegmentationPaletteMode, Record<string, string>> = {
    clinical: CLINICAL_LABEL_COLORS,
    color_safe: COLOR_SAFE_LABEL_COLORS,
};

export const normalizeSegmentationKey = (value: string | null | undefined): string =>
    (value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');

export const resolveSegmentationGroupKey = (value: string): string =>
    value.startsWith('nodule_') ? 'nodule' : value;

export const getSegmentationPaletteTokens = (
    mode: SegmentationPaletteMode,
): SegmentationPaletteTokens => PALETTE_TOKENS[mode];

export const resolveSegmentationLabelColor = (
    labelOrKey: Pick<SegmentationLabel, 'key' | 'color'> | string,
    mode: SegmentationPaletteMode,
): string => {
    const fallbackColor = typeof labelOrKey === 'string'
        ? undefined
        : labelOrKey.color;
    const key = normalizeSegmentationKey(
        typeof labelOrKey === 'string' ? labelOrKey : labelOrKey.key,
    );
    const palette = SEGMENTATION_LABEL_COLORS[mode];
    const groupedKey = resolveSegmentationGroupKey(key);

    return palette[key] ?? palette[groupedKey] ?? fallbackColor ?? PALETTE_TOKENS[mode].nodule;
};

export const getDisplaySegmentationLabels = (
    labels: SegmentationLabel[],
    mode: SegmentationPaletteMode,
): SegmentationLabel[] =>
    labels.map((label) => ({
        ...label,
        color: resolveSegmentationLabelColor(label, mode),
    }));
