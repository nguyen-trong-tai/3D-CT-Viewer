import React, { type ButtonHTMLAttributes, type ReactNode } from 'react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: 'default' | 'primary' | 'ghost' | 'danger';
    size?: 'sm' | 'md' | 'lg';
    icon?: ReactNode;
    iconPosition?: 'left' | 'right';
    loading?: boolean;
    fullWidth?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
    children,
    variant = 'default',
    size = 'md',
    icon,
    iconPosition = 'left',
    loading = false,
    fullWidth = false,
    disabled,
    style,
    ...props
}) => {
    const sizeStyles: Record<string, React.CSSProperties> = {
        sm: { padding: '6px 12px', fontSize: '0.8rem' },
        md: { padding: '8px 16px', fontSize: '0.875rem' },
        lg: { padding: '12px 24px', fontSize: '1rem' },
    };

    const variantStyles: Record<string, React.CSSProperties> = {
        default: {},
        primary: {
            background: 'var(--accent-primary)',
            borderColor: 'var(--accent-primary)',
            color: 'white',
        },
        ghost: {
            background: 'transparent',
            borderColor: 'transparent',
            color: 'var(--text-secondary)',
        },
        danger: {
            background: 'var(--accent-error)',
            borderColor: 'var(--accent-error)',
            color: 'white',
        },
    };

    return (
        <button
            disabled={disabled || loading}
            style={{
                ...sizeStyles[size],
                ...variantStyles[variant],
                width: fullWidth ? '100%' : 'auto',
                opacity: disabled || loading ? 0.5 : 1,
                cursor: disabled || loading ? 'not-allowed' : 'pointer',
                ...style,
            }}
            {...props}
        >
            {loading && (
                <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    style={{ animation: 'spin 1s linear infinite' }}
                >
                    <path d="M21 12a9 9 0 11-6.219-8.56" />
                </svg>
            )}
            {!loading && icon && iconPosition === 'left' && icon}
            {children}
            {!loading && icon && iconPosition === 'right' && icon}
        </button>
    );
};

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    active?: boolean;
    size?: 'sm' | 'md' | 'lg';
    tooltip?: string;
}

export const IconButton: React.FC<IconButtonProps> = ({
    active,
    size = 'md',
    tooltip,
    children,
    disabled,
    style,
    ...props
}) => {
    const sizes: Record<string, number> = {
        sm: 28,
        md: 36,
        lg: 44,
    };

    return (
        <button
            disabled={disabled}
            title={tooltip}
            style={{
                width: sizes[size],
                height: sizes[size],
                padding: 0,
                borderRadius: 'var(--radius-md)',
                background: active ? 'var(--accent-primary)' : 'var(--bg-element)',
                borderColor: active ? 'var(--accent-primary)' : 'var(--border-default)',
                color: active ? 'white' : 'var(--text-secondary)',
                opacity: disabled ? 0.5 : 1,
                cursor: disabled ? 'not-allowed' : 'pointer',
                transition: 'all var(--transition-fast)',
                ...style,
            }}
            {...props}
        >
            {children}
        </button>
    );
};
