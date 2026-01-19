import React, { type InputHTMLAttributes, type ButtonHTMLAttributes } from 'react';


interface SliderProps extends InputHTMLAttributes<HTMLInputElement> {
    label?: string;
    valueDisplay?: string | number;
}

export const RangeSlider: React.FC<SliderProps> = ({ label, valueDisplay, className, style, ...props }) => {
    return (
        <div style={{ marginBottom: '1rem', width: '100%', opacity: props.disabled ? 0.5 : 1, pointerEvents: props.disabled ? 'none' : 'auto' }}>
            {label && (
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <label style={{ color: 'var(--text-scnd)', fontSize: '0.85rem' }}>{label}</label>
                    <span style={{ color: 'var(--accent-primary)', fontSize: '0.85rem', fontWeight: 600 }}>{valueDisplay}</span>
                </div>
            )}
            <input
                type="range"
                style={{
                    width: '100%',
                    cursor: 'pointer',
                    accentColor: 'var(--accent-primary)',
                    ...style
                }}
                {...props}
            />
        </div>
    );
};

interface ToggleProps {
    label: string;
    checked: boolean;
    onChange: (checked: boolean) => void;
    disabled?: boolean;
}

export const ToggleSwitch: React.FC<ToggleProps> = ({ label, checked, onChange, disabled }) => {
    return (
        <div
            style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '1rem',
                cursor: disabled ? 'default' : 'pointer',
                opacity: disabled ? 0.5 : 1,
                pointerEvents: disabled ? 'none' : 'auto'
            }}
            onClick={() => !disabled && onChange(!checked)}
        >
            <label style={{ cursor: disabled ? 'default' : 'pointer', color: 'var(--text-main)' }}>{label}</label>
            <div style={{
                width: '40px',
                height: '24px',
                background: checked ? 'var(--accent-primary)' : 'var(--bg-element)',
                borderRadius: '20px',
                position: 'relative',
                transition: 'background 0.3s'
            }}>
                <div style={{
                    position: 'absolute',
                    top: '2px',
                    left: checked ? '18px' : '2px',
                    width: '20px',
                    height: '20px',
                    background: 'white',
                    borderRadius: '50%',
                    transition: 'left 0.3s',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.3)'
                }} />
            </div>
        </div>
    );
};

export const IconButton: React.FC<ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }> = ({ active, children, style, disabled, ...props }) => {
    return (
        <button
            disabled={disabled}
            style={{
                background: active ? 'var(--accent-primary)' : 'var(--bg-element)',
                borderColor: active ? 'var(--accent-primary)' : 'var(--border-subtle)',
                color: active ? '#fff' : 'var(--text-main)',
                justifyContent: 'center',
                opacity: disabled ? 0.5 : 1,
                cursor: disabled ? 'not-allowed' : 'pointer',
                ...style
            }}
            {...props}
        >
            {children}
        </button>
    );
};
