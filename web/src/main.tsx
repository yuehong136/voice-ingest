import { StrictMode, Component, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiError } from './api'
import App from './App'
import '@fontsource-variable/dm-sans'
import '@fontsource-variable/manrope'
import './styles.css'
const client = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => count < 2 && !(error instanceof ApiError && error.status < 500),
      staleTime: 10000,
    },
    mutations: { retry: false },
  },
})
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? (
      <div className="fatal">
        <h1>Unable to display this workspace</h1>
        <p>Reload to reconnect. Submitted jobs continue on the backend.</p>
        <button onClick={() => location.reload()}>Reload</button>
      </div>
    ) : (
      this.props.children
    )
  }
}
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Boundary>
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>
    </Boundary>
  </StrictMode>,
)
