import React from 'react';
import { Layers, Box, Link2 } from 'lucide-react';

export type ViewMode = '2D' | '3D' | 'LINKED';

interface ViewModeSelectorProps {
    mode: ViewMode;
    onChange: (mode: ViewMode) => void;
}

export const ViewModeSelector: React.FC<ViewModeSelectorProps> = ({ mode, onChange }) => {
    return (
        <div className="view-mode-selector" style={{
            display: 'flex',
            background: 'var(--bg-element)',
            padding: '4px',
            borderRadius: '8px',
            marginBottom: '1rem',
            border: '1px solid var(--border-subtle)'
        }}>
            <button
                className={`mode-btn ${mode === '2D' ? 'active' : ''}`}
                onClick={() => onChange('2D')}
                style={btnStyle(mode === '2D')}
                title="2D Slice View Only"
            >
                <Layers size={16} />
                <span>2D Only</span>
            </button>

            <button
                className={`mode-btn ${mode === 'LINKED' ? 'active' : ''}`}
                onClick={() => onChange('LINKED')}
                style={btnStyle(mode === 'LINKED')}
                title="Linked 2D and 3D Views"
            >
                <Link2 size={16} />
                <span>Linked</span>
            </button>

            <button
                className={`mode-btn ${mode === '3D' ? 'active' : ''}`}
                onClick={() => onChange('3D')}
                style={btnStyle(mode === '3D')}
                title="3D Mesh View Only"
            >
                <Box size={16} />
                <span>3D Only</span>
            </button>
        </div>
    );
};

const btnStyle = (isActive: boolean): React.CSSProperties => ({
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '6px',
    padding: '8px',
    border: 'none',
    borderRadius: '6px',
    background: isActive ? 'var(--accent-primary)' : 'transparent',
    color: isActive ? '#fff' : 'var(--text-scnd)',
    cursor: 'pointer',
    fontSize: '0.85rem',
    fontWeight: 500,
    transition: 'all 0.2s ease',
});
