import React, { useEffect, useRef } from 'react';
import { useViewerStore } from '../../stores/viewerStore';
import { Divider, InfoRow } from '../UI';

const formatVolume = (volumeMm3: number, volumeMl: number): string =>
    volumeMl >= 0.1 ? `${volumeMl.toFixed(2)} ml` : `${volumeMm3.toFixed(1)} mm3`;

const formatConfidence = (score?: number): string | null =>
    typeof score === 'number' ? `AI ${Math.round(score * 100)}%` : null;

export const PatientInfoPanel: React.FC = () => {
    const metadata = useViewerStore((state) => state.metadata);
    const viewMode = useViewerStore((state) => state.viewMode);
    const noduleEntities = useViewerStore((state) => state.noduleEntities);
    const selectedNoduleId = useViewerStore((state) => state.selectedNoduleId);
    const focusNodule = useViewerStore((state) => state.focusNodule);
    const clearNoduleSelection = useViewerStore((state) => state.clearNoduleSelection);

    const selectedItemRef = useRef<HTMLButtonElement | null>(null);
    const is3DContext = viewMode === '3D' || viewMode === 'MPR_3D';
    const selectedNodule = noduleEntities.find((nodule) => nodule.id === selectedNoduleId) ?? null;

    useEffect(() => {
        selectedItemRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }, [selectedNoduleId]);

    if (!metadata) {
        return null;
    }

    return (
        <div
            style={{
                position: 'absolute',
                top: 16,
                right: 16,
                width: 320,
                maxHeight: 'calc(100% - 32px)',
                background: 'rgba(16, 26, 45, 0.75)',
                backdropFilter: 'blur(12px)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
                padding: 'var(--space-md)',
                zIndex: 40,
                color: 'var(--text-primary)',
                boxShadow: 'var(--shadow-lg)',
                pointerEvents: 'none',
                overflow: 'hidden',
            }}
        >
            <h4
                style={{
                    margin: '0 0 var(--space-sm) 0',
                    fontSize: '0.85rem',
                    color: 'var(--accent-primary)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                }}
            >
                Case Information
            </h4>

            <div style={{ pointerEvents: 'auto' }}>
                <InfoRow label="Case ID" value={metadata.id.slice(0, 12)} mono />
                <InfoRow label="Status" value={metadata.status} mono />
                <InfoRow label="Dimension" value={metadata.dimensions.join(' x ')} mono />
                <InfoRow label="Spacing" value={metadata.voxelSpacing.map((v) => v.toFixed(2)).join(' x ')} mono />
                <InfoRow label="Slices" value={metadata.totalSlices} mono />
                {metadata.huRange && (
                    <InfoRow
                        label="HU Range"
                        value={`${metadata.huRange.min.toFixed(0)} ~ ${metadata.huRange.max.toFixed(0)}`}
                        mono
                    />
                )}
            </div>

            {is3DContext ? (
                <>
                    <Divider />
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: 'var(--space-sm)',
                            marginBottom: 'var(--space-sm)',
                        }}
                    >
                        <h4
                            style={{
                                margin: 0,
                                fontSize: '0.85rem',
                                color: 'var(--accent-primary)',
                                textTransform: 'uppercase',
                                letterSpacing: '0.05em',
                            }}
                        >
                            Nodule List
                        </h4>
                        <span
                            style={{
                                padding: '2px 8px',
                                borderRadius: '999px',
                                background: 'rgba(249, 115, 22, 0.16)',
                                color: '#fdba74',
                                fontSize: '0.72rem',
                                fontWeight: 600,
                            }}
                        >
                            {noduleEntities.length} nodule{noduleEntities.length === 1 ? '' : 's'}
                        </span>
                    </div>

                    {selectedNodule && (
                        <div
                            style={{
                                pointerEvents: 'auto',
                                marginBottom: 'var(--space-sm)',
                                padding: '12px',
                                borderRadius: 'var(--radius-md)',
                                border: '1px solid rgba(249, 115, 22, 0.35)',
                                background: 'linear-gradient(180deg, rgba(249, 115, 22, 0.16) 0%, rgba(255, 255, 255, 0.04) 100%)',
                            }}
                        >
                            <div
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    gap: 'var(--space-sm)',
                                    marginBottom: 10,
                                }}
                            >
                                <div>
                                    <div style={{ fontSize: '0.72rem', color: '#fdba74', fontWeight: 700, marginBottom: 4 }}>
                                        Selected Nodule
                                    </div>
                                    <div style={{ fontSize: '0.92rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                                        {selectedNodule.display_name}
                                    </div>
                                </div>
                                <button
                                    type="button"
                                    onClick={() => clearNoduleSelection()}
                                    style={{
                                        padding: '5px 9px',
                                        borderRadius: '999px',
                                        border: '1px solid rgba(255,255,255,0.12)',
                                        background: 'rgba(255,255,255,0.06)',
                                        color: 'var(--text-secondary)',
                                        fontSize: '0.7rem',
                                        fontWeight: 700,
                                        cursor: 'pointer',
                                    }}
                                >
                                    X
                                </button>
                            </div>

                            <div
                                style={{
                                    display: 'grid',
                                    gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
                                    gap: 8,
                                    fontSize: '0.74rem',
                                }}
                            >
                                <InfoRow label="Volume" value={formatVolume(selectedNodule.volume_mm3, selectedNodule.volume_ml)} mono />
                                <InfoRow label="Diameter" value={`${selectedNodule.estimated_diameter_mm.toFixed(1)} mm`} mono />
                                <InfoRow label="Slices" value={`${selectedNodule.slice_range[0]}-${selectedNodule.slice_range[1]}`} mono />
                                <InfoRow label="Voxels" value={selectedNodule.voxel_count.toLocaleString()} mono />
                            </div>

                            <div style={{ marginTop: 8, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                {/* <div style={{ marginBottom: 4 }}>
                                    Centroid: <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{formatCentroid(selectedNodule.centroid_xyz)}</span>
                                </div> */}
                                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                                    <span>{formatConfidence(selectedNodule.detection_score_probability) ?? 'Connected component'}</span>
                                    
                                </div>
                            </div>
                        </div>
                    )}

                    <div
                        style={{
                            pointerEvents: 'auto',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 'var(--space-sm)',
                            maxHeight: 360,
                            overflowY: 'auto',
                            paddingRight: 2,
                            // left align
                        }}
                    >
                        {noduleEntities.map((nodule) => {
                            const isSelected = selectedNoduleId === nodule.id;
                            const confidenceLabel = formatConfidence(nodule.detection_score_probability);

                            return (
                                <button
                                    key={nodule.id}
                                    ref={isSelected ? selectedItemRef : null}
                                    onClick={() => focusNodule(nodule.id)}
                                    aria-pressed={isSelected}
                                    title={isSelected ? `Clear focus for ${nodule.display_name}` : `Focus ${nodule.display_name}`}
                                    style={{
                                        width: '100%',
                                        display: 'grid',
                                        gridTemplateColumns: 'minmax(0, 1fr) auto auto auto',
                                        alignItems: 'center',
                                        columnGap: 10,
                                        textAlign: 'left',
                                        border: '1px solid',
                                        borderColor: isSelected ? 'rgba(249, 115, 22, 0.65)' : 'var(--border-subtle)',
                                        borderRadius: 'var(--radius-md)',
                                        background: isSelected ? 'rgba(249, 115, 22, 0.14)' : 'rgba(255, 255, 255, 0.03)',
                                        padding: '10px 12px',
                                        cursor: 'pointer',
                                        transition: 'border-color var(--transition-fast), background var(--transition-fast), transform var(--transition-fast)',
                                    }}
                                >
                                    <div
                                        style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: 8,
                                            minWidth: 0,
                                        }}
                                    >
                                        <span
                                            style={{
                                                width: 10,
                                                height: 10,
                                                flexShrink: 0,
                                                borderRadius: '50%',
                                                background: '#f41d06',
                                                boxShadow: '0 0 12px rgba(249, 115, 22, 0.55)',
                                            }}
                                        />
                                        <span
                                            style={{
                                                minWidth: 0,
                                                overflow: 'hidden',
                                                textOverflow: 'ellipsis',
                                                whiteSpace: 'nowrap',
                                                fontSize: '0.88rem',
                                                fontWeight: 600,
                                                color: 'var(--text-primary)',
                                            }}
                                        >
                                            {nodule.display_name}
                                        </span>
                                    </div>

                                    <span
                                        style={{
                                            flexShrink: 0,
                                            padding: '4px 8px',
                                            borderRadius: '999px',
                                            background: isSelected ? 'rgba(249, 115, 22, 0.12)' : 'rgba(255, 255, 255, 0.05)',
                                            border: '1px solid rgba(255, 255, 255, 0.06)',
                                            color: 'var(--text-secondary)',
                                            fontSize: '0.7rem',
                                            fontWeight: 600,
                                            whiteSpace: 'nowrap',
                                            lineHeight: 1.2,
                                        }}
                                    >
                                        {nodule.estimated_diameter_mm.toFixed(1)} mm
                                    </span>

                                    <span
                                        style={{
                                            flexShrink: 0,
                                            color: 'var(--text-muted)',
                                            fontSize: '0.71rem',
                                            fontWeight: 600,
                                            whiteSpace: 'nowrap',
                                        }}
                                    >
                                        {nodule.voxel_count.toLocaleString()} vox
                                    </span>

                                    <span
                                        style={{
                                            justifySelf: 'end',
                                            minWidth: 0,
                                            maxWidth: 108,
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                            color: isSelected ? '#fdba74' : 'var(--text-muted)',
                                            fontSize: '0.71rem',
                                            fontWeight: isSelected ? 700 : 600,
                                        }}
                                    >
                                        {confidenceLabel ?? 'Connected component'}
                                    </span>
                                </button>
                            );
                        })}

                        {noduleEntities.length === 0 && (
                            <div
                                style={{
                                    borderRadius: 'var(--radius-md)',
                                    border: '1px dashed var(--border-subtle)',
                                    padding: '14px 12px',
                                    color: 'var(--text-muted)',
                                    fontSize: '0.82rem',
                                    lineHeight: 1.5,
                                }}
                            >
                                {metadata.status === 'ready'
                                    ? 'No connected nodule components are available for this case.'
                                    : 'Nodule list will appear here once the 3D nodule meshes are ready.'}
                            </div>
                        )}
                    </div>
                </>
            ) : null}
        </div>
    );
};
