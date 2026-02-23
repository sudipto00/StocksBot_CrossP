import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface SectionErrorBoundaryProps {
  children: ReactNode;
  name?: string;
}

interface SectionErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class SectionErrorBoundary extends Component<SectionErrorBoundaryProps, SectionErrorBoundaryState> {
  constructor(props: SectionErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): SectionErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[SectionErrorBoundary${this.props.name ? `:${this.props.name}` : ''}]`, error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded-lg border border-red-800/50 bg-red-900/10 p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-red-400 text-sm font-medium">
                {this.props.name ? `${this.props.name} failed to load` : 'Section failed to load'}
              </span>
            </div>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="rounded bg-red-800/50 px-3 py-1 text-xs text-red-200 hover:bg-red-800/80"
            >
              Retry
            </button>
          </div>
          {this.state.error && (
            <p className="mt-2 text-xs text-red-400/70 truncate">{this.state.error.message}</p>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}

export default SectionErrorBoundary;
