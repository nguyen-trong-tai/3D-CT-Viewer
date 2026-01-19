import React, { type ReactNode } from 'react';
import { Activity, Layers, Box } from 'lucide-react';
import type { ViewMode } from '../UI/ViewModeSelector';

interface LayoutProps {
    sidebar: ReactNode;
    viewer2D: ReactNode;
    viewer3D: ReactNode;
    viewMode?: ViewMode;
}

export const MainLayout: React.FC<LayoutProps> = ({ sidebar, viewer2D, viewer3D, viewMode = 'LINKED' }) => {
    return (
        <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-app)' }}>
            {/* Header */}
            <header style={{
                height: '60px',
                borderBottom: '1px solid var(--border-subtle)',
                display: 'flex',
                alignItems: 'center',
                padding: '0 24px',
                background: 'var(--bg-panel)',
                zIndex: 10
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ padding: '8px', background: 'rgba(59, 130, 246, 0.1)', borderRadius: '8px' }}>
                        <Activity size={24} color="var(--accent-primary)" />
                    </div>
                    <div>
                        <h1 style={{ fontSize: '1.1rem', marginBottom: '2px' }}>ViewR CT-to-3D</h1>
                        <small>Research Demonstration Platform</small>
                    </div>
                </div>
                <div style={{ flex: 1 }} />
                <div style={{ display: 'flex', gap: '16px' }}>
                    {/* Status indicators can go here */}
                    <span style={{ fontSize: '0.85rem', color: 'var(--text-scnd)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--accent-success)' }}></span>
                        System Ready
                    </span>
                </div>
            </header>

            {/* Body */}
            <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

                {/* Sidebar */}
                <aside style={{
                    width: '320px',
                    background: 'var(--bg-panel)',
                    borderRight: '1px solid var(--border-subtle)',
                    display: 'flex',
                    flexDirection: 'column',
                    overflowY: 'auto',
                    padding: '24px'
                }}>
                    {sidebar}
                </aside>

                {/* Viewers */}
                <main style={{ flex: 1, display: 'flex', flexDirection: 'row', gap: '2px', background: 'var(--border-subtle)' }}>
                    {/* 2D View */}
                    {(viewMode === 'LINKED' || viewMode === '2D') && (
                        <div style={{ flex: 1, position: 'relative', background: '#000', display: 'flex', flexDirection: 'column' }}>
                            <div style={{ position: 'absolute', top: 16, left: 16, zIndex: 5, pointerEvents: 'none' }}>
                                <div style={{ background: 'rgba(0,0,0,0.6)', padding: '4px 8px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <Layers size={14} color="var(--text-scnd)" />
                                    <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-main)' }}>Axial CT</span>
                                </div>
                            </div>
                            {viewer2D}
                        </div>
                    )}

                    {/* 3D View */}
                    {(viewMode === 'LINKED' || viewMode === '3D') && (
                        <div style={{ flex: 1, position: 'relative', background: '#0f1115', display: 'flex', flexDirection: 'column' }}>
                            <div style={{ position: 'absolute', top: 16, left: 16, zIndex: 5, pointerEvents: 'none' }}>
                                <div style={{ background: 'rgba(0,0,0,0.6)', padding: '4px 8px', borderRadius: '4px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                    <Box size={14} color="var(--text-scnd)" />
                                    <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-main)' }}>3D Reconstruction</span>
                                </div>
                            </div>
                            {viewer3D}
                        </div>
                    )}
                </main>
            </div>
        </div>
    );
};
