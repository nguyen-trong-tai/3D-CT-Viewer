import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useViewerStore } from '../../stores/viewerStore';
import { PipelineVisualizer } from '../Pipeline/PipelineVisualizer';

export const PipelineStatusOverlay: React.FC = () => {
    const metadata = useViewerStore((state) => state.metadata);
    const pipelineSteps = useViewerStore((state) => state.pipelineSteps);
    const [isOpen, setIsOpen] = useState(true);

    const runningStep = useMemo(
        () => pipelineSteps.find((step) => step.status === 'running') ?? null,
        [pipelineSteps],
    );

    if (!metadata) {
        return null;
    }

    return (
        <div
            style={{
                position: 'absolute',
                top: 48,
                left: 16,
                zIndex: 45,
                display: 'flex',
                alignItems: 'flex-start',
                gap: 8,
                pointerEvents: 'auto',
            }}
        >
            <button
                type="button"
                onClick={() => setIsOpen((current) => !current)}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '8px 10px',
                    borderRadius: 10,
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                    background: 'rgba(9, 12, 18, 0.84)',
                    color: 'var(--text-primary)',
                    cursor: 'pointer',
                    backdropFilter: 'blur(12px)',
                    boxShadow: '0 12px 30px rgba(0, 0, 0, 0.28)',
                    fontSize: '0.78rem',
                    fontWeight: 700,
                }}
                title={isOpen ? 'Hide pipeline status' : 'Show pipeline status'}
            >
                {isOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                Pipeline
            </button>

            {isOpen && (
                <div
                    style={{
                        position: 'relative',
                        top: 40,
                        left: -96,
                        width: 300,
                        padding: '12px',
                        borderRadius: 12,
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        background: 'rgba(9, 12, 18, 0.84)',
                        backdropFilter: 'blur(12px)',
                        boxShadow: '0 18px 40px rgba(0, 0, 0, 0.32)',
                        color: 'var(--text-primary)',
                    }}
                >
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: 8,
                            marginBottom: 8,
                        }}
                    >
                        <div>
                            <div
                                style={{
                                    fontSize: '0.78rem',
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.05em',
                                    color: '#93c5fd',
                                }}
                            >
                                Pipeline Status
                            </div>
                            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                                {runningStep ? `Current stage: ${runningStep.label}` : 'Waiting for next update'}
                            </div>
                        </div>
                        <span
                            style={{
                                padding: '2px 8px',
                                borderRadius: '999px',
                                background: 'rgba(59, 130, 246, 0.16)',
                                color: '#bfdbfe',
                                fontSize: '0.7rem',
                                fontWeight: 700,
                                textTransform: 'uppercase',
                            }}
                        >
                            {metadata.status}
                        </span>
                    </div>

                    <PipelineVisualizer steps={pipelineSteps} compact />
                </div>
            )}
        </div>
    );
};
