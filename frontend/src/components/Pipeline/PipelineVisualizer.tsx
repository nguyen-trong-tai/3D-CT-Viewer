import React from 'react';
import type { PipelineStep } from '../../types';
import { CheckCircle2, Circle, Loader2 } from 'lucide-react';

interface PipelineProps {
    steps: PipelineStep[];
}

export const PipelineVisualizer: React.FC<PipelineProps> = ({ steps }) => {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h3 style={{ fontSize: '0.9rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Processing Pipeline
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
                {steps.map((step, idx) => (
                    <div key={step.id} style={{ display: 'flex', gap: '12px', paddingBottom: idx === steps.length - 1 ? 0 : '24px', position: 'relative' }}>
                        {/* Connecting Line */}
                        {idx !== steps.length - 1 && (
                            <div style={{
                                position: 'absolute',
                                left: '10px',
                                top: '24px',
                                bottom: '0',
                                width: '2px',
                                background: 'var(--border-subtle)'
                            }} />
                        )}

                        {/* Icon */}
                        <div style={{ zIndex: 1 }}>
                            {step.status === 'completed' && <CheckCircle2 color="var(--accent-success)" size={22} />}
                            {step.status === 'processing' && <Loader2 className="spin" color="var(--accent-primary)" size={22} />}
                            {step.status === 'pending' && <Circle color="var(--border-strong)" size={22} />}
                        </div>

                        {/* Content */}
                        <div>
                            <div style={{
                                fontWeight: 500,
                                color: step.status === 'pending' ? 'var(--text-muted)' : 'var(--text-main)',
                                fontSize: '0.95rem'
                            }}>
                                {step.label}
                            </div>
                            {step.description && (
                                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                                    {step.description}
                                </div>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            <style>{`
        @keyframes spin { 
            from { transform: rotate(0deg); } 
            to { transform: rotate(360deg); } 
        }
        .spin { animation: spin 2s linear infinite; }
      `}</style>
        </div>
    );
};
