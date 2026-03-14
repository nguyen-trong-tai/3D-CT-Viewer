import React, { useState, useRef, useEffect } from 'react';
import { useViewerStore } from '../../stores/viewerStore';
import { Layers, Box, LogOut, RotateCcw, Eye, LayoutTemplate, SquareDashed, MousePointer2, ZoomIn, Hand, RefreshCw, LayoutGrid, Columns, Crosshair } from 'lucide-react';
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
                title="CT Visualization Options"
                disabled={viewMode === '3D'}
                active={showSegmentation}
                colorTheme="cyan"
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '-4px' }}>
                    <SquareDashed size={14} />
                    <label>Overlays</label>
                </div>
                <ToggleSwitch
                    label="Segmentation"
                    checked={showSegmentation}
                    onChange={setShowSegmentation}
                    description="Show segmented lung/tumor regions"
                />
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
                title="Crosshair Tool (MPR)"
                colorTheme="rose"
                disabled={viewMode === '3D'}
                active={activeTool === 'crosshair'}
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
