import React, { useState, useRef, useEffect } from 'react';
import { useViewerStore } from '../../stores/viewerStore';
import { Layers, Box, LogOut, RotateCcw, Eye, LayoutTemplate, MousePointer2, ZoomIn, Hand, RefreshCw, LayoutGrid, Columns, Crosshair } from 'lucide-react';
import { SegmentedControl, ToggleSwitch } from '../UI';

// Custom hook to handle click outside
function useOnClickOutside(ref: React.RefObject<HTMLElement | null>, handler: () => void) {
    useEffect(() => {
        const listener = (event: MouseEvent | TouchEvent) => {
            if (!ref.current || ref.current.contains(event.target as Node)) {
                return;
            }
            handler();
        };
        document.addEventListener('mousedown', listener);
        document.addEventListener('touchstart', listener);
        return () => {
            document.removeEventListener('mousedown', listener);
            document.removeEventListener('touchstart', listener);
        };
    }, [ref, handler]);
}

const ToolbarPopover: React.FC<{
    icon: React.ReactNode;
    title: string;
    children: React.ReactNode;
    disabled?: boolean;
    active?: boolean;
    colorTheme?: 'indigo' | 'cyan' | 'amber' | 'rose' | 'emerald';
}> = ({ icon, title, children, disabled, active, colorTheme = 'indigo' }) => {
    const [isOpen, setIsOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);
    useOnClickOutside(ref, () => setIsOpen(false));

    const themeColors = {
        indigo: { text: '#818cf8', bg: '99, 102, 241' },
        cyan: { text: '#818cf8', bg: '6, 182, 212' },
        amber: { text: '#818cf8', bg: '245, 158, 11' },
        rose: { text: '#818cf8', bg: '244, 63, 94' },
        emerald: { text: '#818cf8', bg: '16, 185, 129' },
    };
    const theme = themeColors[colorTheme];

    return (
        <div ref={ref} style={{ position: 'relative' }}>
            <button
                onClick={() => !disabled && setIsOpen(!isOpen)}
                title={title}
                style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    width: 38, height: 38,
                    border: '1px solid',
                    borderColor: isOpen ? theme.text : 'transparent',
                    borderRadius: 'var(--radius-md)',
                    background: isOpen || active ? `rgba(${theme.bg}, 0.15)` : 'transparent',
                    color: isOpen || active ? theme.text : 'var(--text-secondary)',
                    cursor: disabled ? 'not-allowed' : 'pointer',
                    opacity: disabled ? 0.5 : 1,
                    transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                    position: 'relative',
                    overflow: 'hidden'
                }}
                onMouseEnter={(e) => {
                    if (!disabled && !isOpen) {
                        e.currentTarget.style.background = `rgba(${theme.bg}, 0.1)`;
                        e.currentTarget.style.color = theme.text;
                        e.currentTarget.style.transform = 'translateY(-1px)';
                    }
                }}
                onMouseLeave={(e) => {
                    if (!disabled && !isOpen && !active) {
                        e.currentTarget.style.background = 'transparent';
                        e.currentTarget.style.color = 'var(--text-secondary)';
                        e.currentTarget.style.transform = 'translateY(0)';
                    } else if (isOpen || active) {
                        e.currentTarget.style.transform = 'translateY(0)';
                    }
                }}
            >
                {/* Gradient subtle glow */}
                {(isOpen || active) && (
                    <div style={{
                        position: 'absolute',
                        inset: 0,
                        background: `radial-gradient(circle at center, rgba(${theme.bg}, 0.3) 0%, transparent 70%)`,
                        opacity: 0.8
                    }} />
                )}
                <div style={{ position: 'relative', zIndex: 1, display: 'flex' }}>
                    {icon}
                </div>
            </button>
            {isOpen && (
                <div style={{
                    position: 'absolute',
                    top: '100%',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    marginTop: 8,
                    background: 'var(--bg-panel)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-md)',
                    padding: 'var(--space-md)',
                    boxShadow: 'var(--shadow-lg)',
                    zIndex: 50,
                    minWidth: 260,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 'var(--space-md)'
                }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        {title}
                    </div>
                    {children}
                </div>
            )}
        </div>
    );
};

const IconButton: React.FC<{
    icon: React.ReactNode;
    title: string;
    onClick: () => void;
    disabled?: boolean;
    active?: boolean;
    colorTheme?: 'indigo' | 'cyan' | 'amber' | 'rose' | 'emerald';
}> = ({ icon, title, onClick, disabled, active, colorTheme = 'indigo' }) => {
    const themeColors = {
        indigo: { text: '#818cf8', bg: '99, 102, 241' },
        cyan: { text: '#22d3ee', bg: '6, 182, 212' },
        amber: { text: '#fbbf24', bg: '245, 158, 11' },
        rose: { text: '#fb7185', bg: '244, 63, 94' },
        emerald: { text: '#34d399', bg: '16, 185, 129' },
    };
    const theme = themeColors[colorTheme];

    return (
        <button
            onClick={onClick}
            title={title}
            disabled={disabled}
            style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: 38, height: 38,
                border: '1px solid',
                borderColor: active ? theme.text : 'transparent',
                borderRadius: 'var(--radius-md)',
                background: active ? `rgba(${theme.bg}, 0.15)` : 'transparent',
                color: active ? theme.text : 'var(--text-secondary)',
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.5 : 1,
                transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                position: 'relative',
                overflow: 'hidden'
            }}
            onMouseEnter={(e) => {
                if (!disabled) {
                    e.currentTarget.style.background = `rgba(${theme.bg}, 0.1)`;
                    e.currentTarget.style.color = theme.text;
                    e.currentTarget.style.transform = 'translateY(-1px)';
                }
            }}
            onMouseLeave={(e) => {
                if (!disabled && !active) {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.color = 'var(--text-secondary)';
                    e.currentTarget.style.transform = 'translateY(0)';
                } else if (active) {
                    e.currentTarget.style.transform = 'translateY(0)';
                }
            }}
        >
            <div style={{ position: 'relative', zIndex: 1, display: 'flex' }}>
                {icon}
            </div>
        </button>
    );
};

export const HeaderToolbar: React.FC = () => {
    const {
        viewMode,
        setViewMode,
        showSegmentation,
        setShowSegmentation,
        segmentationLabels,
        segmentationVisibility,
        setSegmentationVisibility,
        meshVisibilityPreset,
        setMeshVisibilityPreset,
        resetCase,
        metadata,
        activeTool,
        setActiveTool
    } = useViewerStore();

    if (!metadata) return null;

    const viewModeOptions = [
        { value: '2D' as const, label: '2D', icon: <Layers size={14} /> },
        { value: '3D' as const, label: '3D', icon: <Box size={14} /> },
        { value: 'MPR' as const, label: 'MPR', icon: <LayoutGrid size={14} /> },
        { value: 'MPR_3D' as const, label: 'MPR+3D', icon: <Columns size={14} /> },
    ];
    const availableLabels = segmentationLabels.filter((label) => label.available);
    const has2DSegments = availableLabels.some((label) => label.render_2d);
    const has3DSegments = availableLabels.some((label) => label.render_3d);
    const has3DLung = availableLabels.some(
        (label) => label.render_3d && (label.key === 'left_lung' || label.key === 'right_lung' || label.key === 'lung')
    );
    const has3DNodule = availableLabels.some(
        (label) => label.render_3d && label.key === 'nodule'
    );
    const supportsNoduleFocus = has3DLung && has3DNodule;
    const is3DViewActive = viewMode === '3D' || viewMode === 'MPR_3D';
    const isMprViewActive = viewMode === 'MPR' || viewMode === 'MPR_3D';

    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-xs)', background: 'transparent', padding: '6px' }}>

            {/* Layout Popover */}
            <ToolbarPopover icon={<LayoutTemplate size={20} />} title="View Layout" colorTheme="indigo">
                <SegmentedControl
                    options={viewModeOptions}
                    value={viewMode}
                    onChange={(val) => setViewMode(val)}
                />
            </ToolbarPopover>

            <div style={{ width: 1, height: 24, background: 'var(--border-subtle)', margin: '0 4px' }} />

            <ToolbarPopover
                icon={<Eye size={20} />}
                title="Segmentation Visibility"
                disabled={!has2DSegments && !has3DSegments}
                active={showSegmentation || availableLabels.some((label) => segmentationVisibility[label.key])}
                colorTheme="cyan"
            >
                {has2DSegments && !is3DViewActive && (
                    <ToggleSwitch
                        label="2D Overlay"
                        checked={showSegmentation}
                        onChange={setShowSegmentation}
                        description="Show segmentation labels on CT slices"
                    />
                )}
                {availableLabels.map((label) => {
                    const isVisible = segmentationVisibility[label.key] ?? label.visible_by_default;
                    const supportedViews = [
                        label.render_2d ? '2D' : null,
                        label.render_3d ? '3D' : null,
                    ].filter(Boolean).join(' + ');

                    return (
                        <ToggleSwitch
                            key={label.key}
                            label={
                                <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <span
                                        style={{
                                            width: 10,
                                            height: 10,
                                            borderRadius: '50%',
                                            background: label.color,
                                            boxShadow: `0 0 0 1px ${label.color}40`,
                                        }}
                                    />
                                    <span>{label.display_name}</span>
                                </span>
                            }
                            checked={isVisible}
                            onChange={(checked) =>
                                setSegmentationVisibility((current) => ({
                                    ...current,
                                    [label.key]: checked,
                                }))
                            }
                            description={supportedViews || 'Available'}
                        />
                    );
                })}
                {!availableLabels.length && (
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        Waiting for backend segmentation masks...
                    </div>
                )}
            </ToolbarPopover>

            <div style={{ width: 1, height: 24, background: 'var(--border-subtle)', margin: '0 4px' }} />

            <ToolbarPopover
                icon={<Box size={20} />}
                title="3D Focus"
                disabled={!supportsNoduleFocus || !is3DViewActive}
                active={meshVisibilityPreset === 'nodule_focus' && is3DViewActive}
                colorTheme="emerald"
            >
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                    Fade the lungs to make the nodule easier to inspect inside the 3D reconstruction.
                </div>
                <SegmentedControl
                    options={[
                        { value: 'default' as const, label: 'Default' },
                        { value: 'nodule_focus' as const, label: 'Nodule Focus' },
                    ]}
                    value={meshVisibilityPreset}
                    onChange={setMeshVisibilityPreset}
                    disabled={!supportsNoduleFocus || !is3DViewActive}
                />
                {!supportsNoduleFocus && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        Available when the case has both 3D lung and nodule meshes.
                    </div>
                )}
                {supportsNoduleFocus && !is3DViewActive && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        Switch to `3D` or `MPR+3D` to use this focus mode.
                    </div>
                )}
            </ToolbarPopover>

            <div style={{ width: 1, height: 24, background: 'var(--border-subtle)', margin: '0 4px' }} />

            {/* Tools */}
            <IconButton
                icon={<MousePointer2 size={18} />}
                title="Default Tool"
                colorTheme="indigo"
                active={activeTool === 'none'}
                onClick={() => setActiveTool('none')}
            />
            <IconButton
                icon={<ZoomIn size={18} />}
                title="Zoom Tool"
                colorTheme="cyan"
                active={activeTool === 'zoom'}
                onClick={() => setActiveTool('zoom')}
            />
            <IconButton
                icon={<Hand size={18} />}
                title="Pan Tool"
                colorTheme="amber"
                active={activeTool === 'pan'}
                onClick={() => setActiveTool('pan')}
            />
            <IconButton
                icon={<RefreshCw size={18} />}
                title="Rotate Tool"
                colorTheme="emerald"
                disabled={viewMode === '2D' || viewMode === 'MPR'}
                active={activeTool === 'rotate'}
                onClick={() => setActiveTool('rotate')}
            />
            <IconButton
                icon={<Crosshair size={18} />}
                title="Crosshair Tool"
                colorTheme="rose"
                disabled={!isMprViewActive}
                active={isMprViewActive && activeTool === 'crosshair'}
                onClick={() => setActiveTool('crosshair')}
            />

            <div style={{ width: 1, height: 24, background: 'var(--border-subtle)', margin: '0 4px' }} />

            {/* Actions */}
            <IconButton
                icon={<RotateCcw size={20} />}
                title="Reset View"
                colorTheme="amber"
                onClick={() => window.dispatchEvent(new Event('reset-view'))}
            />

            <IconButton
                icon={<LogOut size={20} />}
                title="Load New Case"
                colorTheme="rose"
                onClick={() => {
                    if (confirm('Are you sure you want to load a new case?')) {
                        resetCase();
                    }
                }}
            />
        </div>
    );
};
