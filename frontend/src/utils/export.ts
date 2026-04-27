export const createExportCanvas = (width: number, height: number): HTMLCanvasElement => {
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width));
    canvas.height = Math.max(1, Math.round(height));
    return canvas;
};

export const canvasToBlob = async (
    canvas: HTMLCanvasElement,
    type = 'image/png',
    quality?: number
): Promise<Blob> =>
    new Promise((resolve, reject) => {
        canvas.toBlob((blob) => {
            if (!blob) {
                reject(new Error('Unable to generate export file.'));
                return;
            }

            resolve(blob);
        }, type, quality);
    });

export const downloadBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = 'noopener';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};

export const downloadUrl = (url: string, filename?: string) => {
    const anchor = document.createElement('a');
    anchor.href = url;
    if (filename) {
        anchor.download = filename;
    }
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
};

export const formatExportTimestamp = (date = new Date()): string => {
    const parts = [
        date.getFullYear().toString().padStart(4, '0'),
        (date.getMonth() + 1).toString().padStart(2, '0'),
        date.getDate().toString().padStart(2, '0'),
        '-',
        date.getHours().toString().padStart(2, '0'),
        date.getMinutes().toString().padStart(2, '0'),
        date.getSeconds().toString().padStart(2, '0'),
    ];

    return parts.join('');
};

export const wait = (durationMs: number) =>
    new Promise<void>((resolve) => {
        window.setTimeout(resolve, durationMs);
    });

export const getSupportedVideoMimeType = (): string => {
    const candidates = [
        'video/webm;codecs=vp9',
        'video/webm;codecs=vp8',
        'video/webm',
    ];

    for (const candidate of candidates) {
        if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(candidate)) {
            return candidate;
        }
    }

    return 'video/webm';
};
