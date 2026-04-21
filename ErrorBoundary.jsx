import React from 'react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '20px', fontFamily: 'monospace' }}>
          <h1>Something went wrong</h1>
          <details>
            <summary>Error details</summary>
            <pre style={{ whiteSpace: 'pre-wrap' }}>
              {this.state.error?.toString()}
            </pre>
          </details>
          <button onClick={() => window.location.reload()}>Reload page</button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
