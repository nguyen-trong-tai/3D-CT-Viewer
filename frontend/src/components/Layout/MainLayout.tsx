import React, { useState, type ReactNode } from 'react';
import { Activity, PanelLeftClose, PanelLeft } from 'lucide-react';
import { ErrorBoundary } from '../UI/ErrorBoundary';
import type { ViewMode } from '../../types';

interface MainLayoutProps {
    sidebar: ReactNode;
    viewer2D: ReactNode;
    viewer3D: ReactNode | null;
    viewMode: ViewMode;
}

/**
 * Main Layout Component
 * Provides the overall structure for the viewer:
 * - Header with branding and status
 * - Collapsible sidebar for controls
 * - Main content area with 2D/3D viewers
 */
export const MainLayout: React.FC<MainLayoutProps> = ({
    sidebar,
    viewer2D,
    viewer3D,
    viewMode,
}) => {
    const [sidebarOpen, setSidebarOpen] = useState(true);

    const toggleSidebar = () => {
        setSidebarOpen(prev => !prev);
    };

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
                    borderBottom: '1px solid var(--border-subtle)',
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0 var(--space-lg)',
                    background: 'var(--bg-panel)',
                    zIndex: 20,
                }}
            >
                {/* Sidebar Toggle Button */}
                <button
                    onClick={toggleSidebar}
                    title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
                    aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: 36,
                        height: 36,
                        borderRadius: 'var(--radius-md)',
                        background: 'var(--bg-element)',
                        border: '1px solid var(--border-subtle)',
                        color: 'var(--text-secondary)',
                        cursor: 'pointer',
                        marginRight: 'var(--space-md)',
                        transition: 'all var(--transition-fast)',
                    }}
                    onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'var(--bg-element-hover)';
                        e.currentTarget.style.borderColor = 'var(--border-default)';
                        e.currentTarget.style.color = 'var(--text-primary)';
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'var(--bg-element)';
                        e.currentTarget.style.borderColor = 'var(--border-subtle)';
                        e.currentTarget.style.color = 'var(--text-secondary)';
                    }}
                >
                    {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeft size={18} />}
                </button>

                {/* Logo & Title */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)' }}>
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

                <div style={{ flex: 1 }} />

                {/* Status Indicator */}
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--space-sm)',
                        padding: 'var(--space-xs) var(--space-sm)',
                        background: 'var(--accent-success-glow)',
                        borderRadius: 'var(--radius-full)',
                        border: '1px solid rgba(16, 185, 129, 0.3)',
                    }}
                >
                    <span
                        style={{
                            width: 6,
                            height: 6,
                            borderRadius: '50%',
                            background: 'var(--accent-success)',
                            animation: 'pulse 2s ease-in-out infinite',
                        }}
                    />
                    <span
                        style={{
                            fontSize: '0.75rem',
                            color: 'var(--accent-success)',
                            fontWeight: 500,
                        }}
                    >
                        System Ready
                    </span>
                </div>
            </header>

            {/* Body */}
            <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                {/* Sidebar */}
                <aside
                    style={{
                        width: sidebarOpen ? 320 : 0,
                        minWidth: sidebarOpen ? 320 : 0,
                        background: 'var(--bg-panel)',
                        borderRight: sidebarOpen ? '1px solid var(--border-subtle)' : 'none',
                        display: 'flex',
                        flexDirection: 'column',
                        overflow: 'hidden',
                        transition: 'width var(--transition-slow), min-width var(--transition-slow), border-right var(--transition-slow)',
                    }}
                >
                    <div
                        style={{
                            padding: 'var(--space-lg)',
                            flex: 1,
                            overflowY: 'auto',
                            overflowX: 'hidden',
                            opacity: sidebarOpen ? 1 : 0,
                            transition: 'opacity var(--transition-fast)',
                            pointerEvents: sidebarOpen ? 'auto' : 'none',
                        }}
                    >
                        {sidebar}
                    </div>
                </aside>

                {/* Viewers */}
                <main
                    style={{
                        flex: 1,
                        display: 'flex',
                        flexDirection: 'row',
                        gap: 2,
                        background: '#000',
                        overflow: 'hidden',
                    }}
                >
                    {/* 2D View */}
                    {viewMode === '2D' && (
                        <div
                            style={{
                                flex: 1,
                                position: 'relative',
                                background: '#000',
                                display: 'flex',
                                flexDirection: 'column',
                            }}
                        >
                            <ErrorBoundary>
                                {viewer2D}
                            </ErrorBoundary>
                        </div>
                    )}

                    {/* 3D View */}
                    {viewMode === '3D' && viewer3D && (
                        <div
                            style={{
                                flex: 1,
                                position: 'relative',
                                background: 'var(--bg-app)',
                                display: 'flex',
                                flexDirection: 'column',
                            }}
                        >
                            <ErrorBoundary>
                                {viewer3D}
                            </ErrorBoundary>
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
