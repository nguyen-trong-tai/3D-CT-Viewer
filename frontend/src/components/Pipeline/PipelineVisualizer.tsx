import React from 'react';
import type { PipelineStep } from '../../types';
import { CheckCircle2, Circle, Loader2, AlertCircle } from 'lucide-react';

interface PipelineVisualizerProps {
    steps: PipelineStep[];
    compact?: boolean;
}

/**
 * Pipeline Visualizer Component
 * Displays the AI processing stages as per PRD:
 * CT → Segmentation → SDF → Marching Cubes → Mesh
 */
export const PipelineVisualizer: React.FC<PipelineVisualizerProps> = ({ steps, compact = false }) => {
    const getStatusIcon = (status: PipelineStep['status']) => {
        switch (status) {
            case 'completed':
                return <CheckCircle2 size={compact ? 16 : 20} color="var(--accent-success)" />;
            case 'running':
                return (
                    <Loader2
                        size={compact ? 16 : 20}
                        color="var(--accent-primary)"
                        style={{ animation: 'spin 1s linear infinite' }}
                    />
                );
            case 'failed':
                return <AlertCircle size={compact ? 16 : 20} color="var(--accent-error)" />;
            default:
                return <Circle size={compact ? 16 : 20} color="var(--text-muted)" />;
        }
    };

    const getStatusColor = (status: PipelineStep['status']) => {
        switch (status) {
            case 'completed':
                return 'var(--accent-success)';
            case 'running':
                return 'var(--accent-primary)';
            case 'failed':
                return 'var(--accent-error)';
            default:
                return 'var(--border-strong)';
        }
    };

    return (
        <div
            style={{
                padding: compact ? 'var(--space-sm)' : 'var(--space-md)',
                background: 'var(--bg-panel)',
                borderRadius: 'var(--radius-lg)',
                border: '1px solid var(--border-subtle)',
            }}
        >
            {!compact && (
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-sm)',
                        marginBottom: 'var(--space-md)',
                        paddingBottom: 'var(--space-sm)',
                        borderBottom: '1px solid var(--border-subtle)',
                    }}
                >
                    <div
                        style={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            background: 'var(--accent-primary)',
                            animation: 'pulse 2s ease-in-out infinite',
                        }}
                    />
                    <span
                        style={{
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            textTransform: 'uppercase',
                            letterSpacing: '0.1em',
                            color: 'var(--text-muted)',
                        }}
                    >
                        AI Pipeline
                    </span>
                </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                {steps.map((step, idx) => (
                    <div
                        key={step.id}
                        style={{
                            display: 'flex',
                            gap: compact ? 'var(--space-sm)' : 'var(--space-md)',
                            position: 'relative',
                            paddingBottom: idx === steps.length - 1 ? 0 : compact ? 12 : 20,
                        }}
                    >
                        {/* Connecting Line */}
                        {idx !== steps.length - 1 && (
                            <div
                                style={{
                                    position: 'absolute',
                                    left: compact ? 7 : 9,
                                    top: compact ? 18 : 22,
                                    bottom: 0,
                                    width: 2,
                                    background:
                                        step.status === 'completed'
                                            ? 'var(--accent-success)'
                                            : step.status === 'running'
                                                ? `linear-gradient(to bottom, var(--accent-primary), var(--border-subtle))`
                                                : 'var(--border-subtle)',
                                    borderRadius: 1,
                                }}
                            />
                        )}

                        {/* Icon with glow effect for active step */}
                        <div
                            style={{
                                position: 'relative',
                                zIndex: 1,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                width: compact ? 16 : 20,
                                height: compact ? 16 : 20,
                            }}
                        >
                            {step.status === 'running' && (
                                <div
                                    style={{
                                        position: 'absolute',
                                        inset: -4,
                                        borderRadius: '50%',
                                        background: 'var(--accent-primary-glow)',
                                        animation: 'pulse 2s ease-in-out infinite',
                                    }}
                                />
                            )}
                            {getStatusIcon(step.status)}
                        </div>

                        {/* Content */}
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div
                                style={{
                                    fontWeight: 500,
                                    fontSize: compact ? '0.8rem' : '0.9rem',
                                    color:
                                        step.status === 'pending'
                                            ? 'var(--text-muted)'
                                            : step.status === 'failed'
                                                ? 'var(--accent-error)'
                                                : 'var(--text-primary)',
                                    lineHeight: 1.3,
                                }}
                            >
                                {step.label}
                            </div>
                            {!compact && step.description && (
                                <div
                                    style={{
                                        fontSize: '0.75rem',
                                        color: 'var(--text-muted)',
                                        marginTop: 2,
                                        lineHeight: 1.4,
                                    }}
                                >
                                    {step.description}
                                </div>
                            )}
                            {step.duration && step.status === 'completed' && (
                                <div
                                    style={{
                                        fontSize: '0.7rem',
                                        color: 'var(--text-muted)',
                                        fontFamily: 'var(--font-mono)',
                                        marginTop: 2,
                                    }}
                                >
                                    {(step.duration / 1000).toFixed(1)}s
                                </div>
                            )}
                        </div>

                        {/* Status badge for compact mode */}
                        {compact && (
                            <div
                                style={{
                                    width: 6,
                                    height: 6,
                                    borderRadius: '50%',
                                    background: getStatusColor(step.status),
                                    alignSelf: 'center',
                                }}
                            />
                        )}
                    </div>
                ))}
            </div>

            {/* Styles for animations */}
            <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
        </div>
    );
};
