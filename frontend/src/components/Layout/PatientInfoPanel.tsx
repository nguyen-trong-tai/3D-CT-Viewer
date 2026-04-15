import React from 'react';
import { useViewerStore } from '../../stores/viewerStore';
import { PipelineVisualizer } from '../Pipeline/PipelineVisualizer';
import { InfoRow } from '../UI';

export const PatientInfoPanel: React.FC = () => {
    const metadata = useViewerStore((state) => state.metadata);
    const pipelineSteps = useViewerStore((state) => state.pipelineSteps);

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
                background: 'rgba(15, 17, 21, 0.75)',
                backdropFilter: 'blur(12px)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
                padding: 'var(--space-md)',
                zIndex: 40,
                color: 'var(--text-primary)',
                boxShadow: 'var(--shadow-lg)',
                pointerEvents: 'none',
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

            {pipelineSteps.length > 0 && (
                <>
                    <div
                        style={{
                            margin: 'var(--space-md) 0',
                            borderTop: '1px solid var(--border-subtle)',
                        }}
                    />
                    <h4
                        style={{
                            margin: '0 0 var(--space-sm) 0',
                            fontSize: '0.85rem',
                            color: 'var(--accent-primary)',
                            textTransform: 'uppercase',
                            letterSpacing: '0.05em',
                        }}
                    >
                        Pipeline Status
                    </h4>
                    <div style={{ pointerEvents: 'auto' }}>
                        <PipelineVisualizer steps={pipelineSteps} compact />
                    </div>
                </>
            )}
        </div>
    );
};
