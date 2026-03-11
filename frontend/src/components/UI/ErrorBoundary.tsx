/**
 * Error Boundary — Catch runtime crashes in viewer components
 *
 * Prevents white screen of death when WebGL crashes, volume
 * decoding fails, or Three.js throws unexpected errors.
 */

import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[ErrorBoundary] Caught error:', error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div
          style={{
            width: '100%',
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '16px',
            padding: '32px',
            background: 'var(--bg-primary, #0a0a0f)',
            color: 'var(--text-secondary, #a0a0b0)',
          }}
        >
          <div
            style={{
              width: '48px',
              height: '48px',
              borderRadius: '50%',
              background: 'rgba(239, 68, 68, 0.12)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '24px',
            }}
          >
            ⚠️
          </div>
          <h3 style={{ margin: 0, color: 'var(--text-primary, #e0e0f0)' }}>
            Something went wrong
          </h3>
          <p
            style={{
              margin: 0,
              fontSize: '0.85rem',
              textAlign: 'center',
              maxWidth: '400px',
              lineHeight: 1.5,
            }}
          >
            {this.state.error?.message || 'An unexpected error occurred in this component.'}
          </p>
          <button
            onClick={this.handleRetry}
            style={{
              padding: '8px 20px',
              borderRadius: '6px',
              border: '1px solid var(--border-subtle, #2a2a3a)',
              background: 'var(--bg-element, #16161f)',
              color: 'var(--text-primary, #e0e0f0)',
              cursor: 'pointer',
              fontSize: '0.85rem',
              transition: 'background 0.2s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-hover, #1e1e2e)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--bg-element, #16161f)')}
          >
            Try Again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
