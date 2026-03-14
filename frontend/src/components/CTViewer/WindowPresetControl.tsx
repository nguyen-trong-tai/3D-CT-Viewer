import React, { useState, useRef, useEffect } from 'react';
import { Settings2, ChevronUp, Layers, Wind, Bone, Brain, Activity, Droplet, SlidersHorizontal } from 'lucide-react';
import { WINDOW_PRESETS, type WindowPresetKey } from '../../types';
import { useViewerStore } from '../../stores/viewerStore';

// Custom hook to handle click outside
export function useOnClickOutside(ref: React.RefObject<HTMLElement | null>, handler: () => void) {
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

export const WindowPresetControl = () => {
    const {
        windowPreset,
        applyPreset,
        useCustomWindow,
        setUseCustomWindow,
        customWindowLevel,
        setCustomWindowLevel,
        customWindowWidth,
        setCustomWindowWidth,
    } = useViewerStore();

    const [isOpen, setIsOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);
    useOnClickOutside(ref, () => setIsOpen(false));

    const windowPresetOptions = Object.entries(WINDOW_PRESETS).map(([key, preset]) => ({
        value: key as WindowPresetKey,
        label: preset.name,
    }));

    return (
        <div ref={ref} style={{ position: 'absolute', bottom: 48, left: 12, zIndex: 40 }}>
            {/* Popover */}
            {isOpen && (
                <div 
                    className="animate-slide-up"
                    style={{
                        position: 'absolute',
                        bottom: '100%',
                        left: 0,
                        marginBottom: 8,
                        background: 'var(--bg-panel)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-md)',
                        padding: 'var(--space-md)',
                        boxShadow: 'var(--shadow-lg)',
                        minWidth: 260,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 'var(--space-sm)'
                    }}
                >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        <SlidersHorizontal size={14} />
                        <label style={{ margin: 0 }}>Window Preset</label>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-xs)' }}>
                        {windowPresetOptions.map(opt => {
                            let Icon = Layers;
                            if (opt.value === 'LUNG') Icon = Wind;
                            else if (opt.value === 'BONE') Icon = Bone;
                            else if (opt.value === 'BRAIN') Icon = Brain;
                            else if (opt.value === 'LIVER') Icon = Activity;
                            else if (opt.value === 'SOFT_TISSUE') Icon = Droplet;

                            return (
                                <button
                                    key={opt.value}
                                    onClick={() => {
                                        applyPreset(opt.value);
                                        setIsOpen(false);
                                    }}
                                    style={{
                                        display: 'flex', alignItems: 'center', gap: '8px',
                                        padding: '8px 12px',
                                        background: !useCustomWindow && windowPreset === opt.value ? 'var(--accent-primary)' : 'var(--bg-element)',
                                        color: !useCustomWindow && windowPreset === opt.value ? '#fff' : 'var(--text-secondary)',
                                        border: '1px solid',
                                        borderColor: !useCustomWindow && windowPreset === opt.value ? 'var(--accent-primary)' : 'var(--border-subtle)',
                                        borderRadius: 'var(--radius-sm)',
                                        cursor: 'pointer',
                                        fontSize: '0.75rem',
                                        fontWeight: 500,
                                        transition: 'all 0.2s',
                                        justifyContent: 'flex-start'
                                    }}
                                >
                                    <Icon size={14} />
                                    {opt.label}
                                </button>
                            );
                        })}
                    </div>

                    {/* Custom Window Settings */}
                    <div style={{ marginTop: 'var(--space-xs)', background: 'var(--bg-element)', padding: 'var(--space-sm) var(--space-md)', borderRadius: 'var(--radius-sm)', border: '1px solid', borderColor: useCustomWindow ? 'var(--accent-primary)' : 'var(--border-subtle)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span style={{ fontSize: '0.75rem', color: useCustomWindow ? 'var(--accent-primary)' : 'var(--text-secondary)', fontWeight: 500 }}>Custom Tuning</span>
                            {useCustomWindow && <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent-primary)', boxShadow: '0 0 4px var(--accent-primary)' }} />}
                        </div>
                        
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                <span>Level (WL)</span>
                                <span style={{ fontFamily: 'var(--font-mono)' }}>{customWindowLevel}</span>
                            </div>
                            <input 
                                type="range" 
                                min="-1000" max="1000" 
                                value={customWindowLevel} 
                                onChange={(e) => {
                                    setUseCustomWindow(true);
                                    setCustomWindowLevel(Number(e.target.value));
                                }}
                            />
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                <span>Width (WW)</span>
                                <span style={{ fontFamily: 'var(--font-mono)' }}>{customWindowWidth}</span>
                            </div>
                            <input 
                                type="range" 
                                min="1" max="4000" 
                                value={customWindowWidth} 
                                onChange={(e) => {
                                    setUseCustomWindow(true);
                                    setCustomWindowWidth(Number(e.target.value));
                                }}
                            />
                        </div>
                    </div>
                </div>
            )}
            
            {/* Toggle Button */}
            <button
                onClick={() => setIsOpen(!isOpen)}
                style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    background: isOpen ? 'var(--accent-primary)' : 'rgba(0,0,0,0.7)',
                    backdropFilter: 'blur(4px)',
                    color: isOpen ? '#fff' : 'var(--text-primary)',
                    border: '1px solid',
                    borderColor: isOpen ? 'var(--accent-primary)' : 'rgba(255,255,255,0.1)',
                    padding: '6px 12px',
                    borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer',
                    transition: 'background 0.2s, border-color 0.2s',
                    fontSize: '0.75rem',
                    fontWeight: 500,
                }}
            >
                <Settings2 size={14} color={isOpen ? '#fff' : 'var(--text-secondary)'} />
                {useCustomWindow
                    ? `WL: ${customWindowLevel} / WW: ${customWindowWidth}`
                    : `${WINDOW_PRESETS[windowPreset]?.name || windowPreset}`}
                <ChevronUp size={14} style={{ transform: isOpen ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 0.2s', marginLeft: 4, color: isOpen ? '#fff' : 'var(--text-secondary)' }} />
            </button>
        </div>
    );
};
