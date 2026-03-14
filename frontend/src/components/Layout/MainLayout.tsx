import React, { useState, type ReactNode } from 'react';
import { Activity, Info } from 'lucide-react';
import { ErrorBoundary } from '../UI/ErrorBoundary';
import { HeaderToolbar } from './HeaderToolbar';
import { PatientInfoPanel } from './PatientInfoPanel';
import type { ViewMode } from '../../types';

interface MainLayoutProps {
    viewer2D: ReactNode;
    viewer2D_coronal?: ReactNode;
    viewer2D_sagittal?: ReactNode;
    viewer3D: ReactNode | null;
    viewMode: ViewMode;
}

/**
 * Main Layout Component
 * Provides the overall structure for the viewer:
 * - Header with branding and control toolbar
 * - Main content area with 2D/3D viewers and info overlays
 */
export const MainLayout: React.FC<MainLayoutProps> = ({
    viewer2D,
    viewer2D_coronal,
    viewer2D_sagittal,
    viewer3D,
    viewMode,
}) => {
    const [showInfoPanel, setShowInfoPanel] = useState(true);
    return (
        <div
            style={{
                height: '100vh',
                display: 'flex',
                flexDirection: 'column',
                background: 'var(--bg-app)',
                overflow: 'hidden',
            }}
        >
            {/* Header */}
            <header
                style={{
                    height: 56,
                    minHeight: 56,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0 var(--space-lg)',
                    background: '#072848ff',
                    zIndex: 20,
                    borderBottom: '1px solid rgba(82, 137, 224, 0.3)',
                }}
            >
                {/* Logo & Title */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', flex: 1 }}>
                    <div
                        style={{
                            width: 36,
                            height: 36,
                            borderRadius: 'var(--radius-md)',
                            background: 'var(--gradient-primary)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            boxShadow: 'var(--shadow-glow)',
                        }}
                    >
                        <Activity size={20} color="white" />
                    </div>
                    <div>
                        <h1
                            style={{
                                fontSize: '1rem',
                                fontWeight: 600,
                                color: 'var(--text-primary)',
                                lineHeight: 1.2,
                            }}
                        >
                            ViewR CT
                        </h1>
                        <span
                            style={{
                                fontSize: '0.7rem',
                                color: 'var(--text-muted)',
                                textTransform: 'uppercase',
                                letterSpacing: '0.05em',
                            }}
                        >
                            Medical Research Platform
                        </span>
                    </div>
                </div>

                {/* Main Toolbar Controls */}
                <div style={{ display: 'flex', justifyContent: 'center' }}>
                    <HeaderToolbar />
                </div>

                {/* Toggle Info Panel */}
                <div style={{ display: 'flex', justifyContent: 'flex-end', flex: 1 }}>
                    <button
                        onClick={() => setShowInfoPanel(!showInfoPanel)}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                            background: showInfoPanel ? 'var(--accent-primary)' : 'rgba(0, 0, 0, 0.2)',
                            color: showInfoPanel ? '#fff' : 'rgba(255, 255, 255, 0.7)',
                            border: '1px solid',
                            borderColor: showInfoPanel ? 'var(--accent-primary)' : 'rgba(255, 255, 255, 0.2)',
                            padding: '6px 12px',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.8rem',
                            cursor: 'pointer',
                            transition: 'all 0.2s',
                        }}
                        title={showInfoPanel ? 'Hide Info Panel' : 'Show Info Panel'}
                    >
                        <Info size={14} />
                        Info
                    </button>
                </div>
            </header>

            {/* Body */}
            <div style={{ flex: 1, display: 'flex', position: 'relative', overflow: 'hidden' }}>
                {/* Viewers */}
                <main
                    style={{
                        flex: 1,
                        display: 'flex',
                        flexDirection: 'row',
                        gap: 2,
                        background: '#000',
                        overflow: 'hidden',
                        position: 'relative'
                    }}
                >
                    {/* Floating Info Panel Overlay */}
                    {showInfoPanel && <PatientInfoPanel />}
                    {/* 2D View */}
                    {viewMode === '2D' && (
                        <div style={{ flex: 1, position: 'relative', background: '#000', display: 'flex', flexDirection: 'column' }}>
                            <ErrorBoundary>{viewer2D}</ErrorBoundary>
                        </div>
                    )}

                    {/* 3D View */}
                    {viewMode === '3D' && viewer3D && (
                        <div style={{ flex: 1, position: 'relative', background: 'var(--bg-app)', display: 'flex', flexDirection: 'column' }}>
                            <ErrorBoundary>{viewer3D}</ErrorBoundary>
                        </div>
                    )}

                    {/* MPR View (1x3 Grid) */}
                    {viewMode === 'MPR' && (
                        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 2, background: '#222' }}>
                            <div style={{ position: 'relative', background: '#000', display: 'flex', flexDirection: 'column' }}>
                                <ErrorBoundary>{viewer2D}</ErrorBoundary>
                            </div>
                            <div style={{ position: 'relative', background: '#000', display: 'flex', flexDirection: 'column' }}>
                                <ErrorBoundary>{viewer2D_sagittal || viewer2D}</ErrorBoundary>
                            </div>
                            <div style={{ position: 'relative', background: '#000', display: 'flex', flexDirection: 'column' }}>
                                <ErrorBoundary>{viewer2D_coronal || viewer2D}</ErrorBoundary>
                            </div>
                        </div>
                    )}

                    {/* MPR + 3D View (2x2 Grid) */}
                    {viewMode === 'MPR_3D' && (
                        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gridTemplateRows: '1fr 1fr', gap: 2, background: '#222' }}>
                            <div style={{ position: 'relative', background: '#000', display: 'flex', flexDirection: 'column' }}>
                                <ErrorBoundary>{viewer2D}</ErrorBoundary>
                            </div>
                            <div style={{ position: 'relative', background: '#000', display: 'flex', flexDirection: 'column' }}>
                                <ErrorBoundary>{viewer2D_sagittal || viewer2D}</ErrorBoundary>
                            </div>
                            <div style={{ position: 'relative', background: '#000', display: 'flex', flexDirection: 'column' }}>
                                <ErrorBoundary>{viewer2D_coronal || viewer2D}</ErrorBoundary>
                            </div>
                            <div style={{ position: 'relative', background: 'var(--bg-app)', display: 'flex', flexDirection: 'column' }}>
                                <ErrorBoundary>{viewer3D}</ErrorBoundary>
                            </div>
                        </div>
                    )}
                </main>
            </div>

            {/* Animation keyframes */}
            <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
        </div>
    );
};
