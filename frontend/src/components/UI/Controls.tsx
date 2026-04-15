import React, { type InputHTMLAttributes, type ReactNode } from 'react';

/**
 * Range Slider with label and value display
 */
interface RangeSliderProps extends InputHTMLAttributes<HTMLInputElement> {
    label?: string;
    valueDisplay?: string | number;
    showValue?: boolean;
}

export const RangeSlider: React.FC<RangeSliderProps> = ({
    label,
    valueDisplay,
    showValue = true,
    disabled,
    style,
    ...props
}) => {
    return (
        <div
            style={{
                marginBottom: 'var(--space-md)',
                opacity: disabled ? 0.5 : 1,
                pointerEvents: disabled ? 'none' : 'auto',
            }}
        >
            {label && (
                <div
                    style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: 'var(--space-sm)',
                    }}
                >
                    <label style={{ margin: 0 }}>{label}</label>
                    {showValue && valueDisplay !== undefined && (
                        <span
                            style={{
                                fontSize: '0.85rem',
                                fontWeight: 600,
                                color: 'var(--accent-primary)',
                                fontFamily: 'var(--font-mono)',
                            }}
                        >
                            {valueDisplay}
                        </span>
                    )}
                </div>
            )}
            <input type="range" style={{ width: '100%', ...style }} disabled={disabled} {...props} />
        </div>
    );
};

/**
 * Toggle Switch
 */
interface ToggleSwitchProps {
    label: ReactNode;
    checked: boolean;
    onChange: (checked: boolean) => void;
    disabled?: boolean;
    description?: ReactNode;
}

export const ToggleSwitch: React.FC<ToggleSwitchProps> = ({
    label,
    checked,
    onChange,
    disabled = false,
    description,
}) => {
    return (
        <div
            style={{
                display: 'flex',
                alignItems: 'flex-start',
                justifyContent: 'space-between',
                gap: 'var(--space-md)',
                marginBottom: 'var(--space-md)',
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.5 : 1,
            }}
            onClick={() => !disabled && onChange(!checked)}
        >
            <div>
                <div
                    style={{
                        fontWeight: 500,
                        fontSize: '0.9rem',
                        color: 'var(--text-primary)',
                    }}
                >
                    {label}
                </div>
                {description && (
                    <div
                        style={{
                            fontSize: '0.75rem',
                            color: 'var(--text-muted)',
                            marginTop: '2px',
                        }}
                    >
                        {description}
                    </div>
                )}
            </div>
            <div
                style={{
                    width: 44,
                    height: 24,
                    background: checked ? 'var(--accent-primary)' : 'var(--bg-element)',
                    borderRadius: 'var(--radius-full)',
                    position: 'relative',
                    transition: 'background var(--transition-base)',
                    flexShrink: 0,
                    border: `1px solid ${checked ? 'var(--accent-primary)' : 'var(--border-default)'}`,
                }}
            >
                <div
                    style={{
                        position: 'absolute',
                        top: 2,
                        left: checked ? 22 : 2,
                        width: 18,
                        height: 18,
                        background: 'white',
                        borderRadius: '50%',
                        transition: 'left var(--transition-fast)',
                        boxShadow: 'var(--shadow-sm)',
                    }}
                />
            </div>
        </div>
    );
};

/**
 * Segmented Control (Tab-like buttons)
 */
interface SegmentedControlProps<T extends string> {
    options: { value: T; label: string; icon?: React.ReactNode }[];
    value: T;
    onChange: (value: T) => void;
    disabled?: boolean;
}

export function SegmentedControl<T extends string>({
    options,
    value,
    onChange,
    disabled = false,
}: SegmentedControlProps<T>) {
    return (
        <div
            style={{
                display: 'flex',
                background: 'var(--bg-element)',
                padding: 4,
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
                gap: 2,
            }}
        >
            {options.map((option) => (
                <button
                    key={option.value}
                    disabled={disabled}
                    onClick={() => onChange(option.value)}
                    style={{
                        flex: 1,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 6,
                        padding: '8px 12px',
                        border: 'none',
                        borderRadius: 'var(--radius-sm)',
                        background: value === option.value ? 'var(--accent-primary)' : 'transparent',
                        color: value === option.value ? 'white' : 'var(--text-secondary)',
                        fontSize: '0.85rem',
                        fontWeight: 500,
                        cursor: disabled ? 'not-allowed' : 'pointer',
                        transition: 'all var(--transition-fast)',
                    }}
                >
                    {option.icon}
                    {option.label}
                </button>
            ))}
        </div>
    );
}

/**
 * Info Row for displaying key-value pairs
 */
interface InfoRowProps {
    label: string;
    value: React.ReactNode;
    mono?: boolean;
}

export const InfoRow: React.FC<InfoRowProps> = ({ label, value, mono = false }) => {
    return (
        <div
            style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: 'var(--space-xs) 0',
            }}
        >
            <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>{label}</span>
            <span
                style={{
                    color: 'var(--text-primary)',
                    fontSize: '0.85rem',
                    fontFamily: mono ? 'var(--font-mono)' : 'inherit',
                    fontWeight: 500,
                }}
            >
                {value}
            </span>
        </div>
    );
};

/**
 * Divider
 */
export const Divider: React.FC<{ spacing?: 'sm' | 'md' | 'lg' }> = ({ spacing = 'md' }) => {
    const margins: Record<string, string> = {
        sm: 'var(--space-sm)',
        md: 'var(--space-md)',
        lg: 'var(--space-lg)',
    };

    return (
        <div
            style={{
                height: 1,
                background: 'var(--border-subtle)',
                margin: `${margins[spacing]} 0`,
            }}
        />
    );
};

/**
 * Progress Bar
 */
interface ProgressBarProps {
    value: number;
    max?: number;
    showLabel?: boolean;
    size?: 'sm' | 'md';
    variant?: 'default' | 'success' | 'warning' | 'error';
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
    value,
    max = 100,
    showLabel = false,
    size = 'md',
    variant = 'default',
}) => {
    const percent = Math.min(100, Math.max(0, (value / max) * 100));

    const heights: Record<string, number> = { sm: 4, md: 8 };

    const colors: Record<string, string> = {
        default: 'var(--gradient-primary)',
        success: 'var(--accent-success)',
        warning: 'var(--accent-warning)',
        error: 'var(--accent-error)',
    };

    return (
        <div>
            <div
                style={{
                    width: '100%',
                    height: heights[size],
                    background: 'var(--bg-element)',
                    borderRadius: 'var(--radius-full)',
                    overflow: 'hidden',
                }}
            >
                <div
                    style={{
                        width: `${percent}%`,
                        height: '100%',
                        background: colors[variant],
                        borderRadius: 'var(--radius-full)',
                        transition: 'width var(--transition-base)',
                    }}
                />
            </div>
            {showLabel && (
                <div
                    style={{
                        textAlign: 'center',
                        fontSize: '0.75rem',
                        color: 'var(--text-muted)',
                        marginTop: 'var(--space-xs)',
                    }}
                >
                    {Math.round(percent)}%
                </div>
            )}
        </div>
    );
};
