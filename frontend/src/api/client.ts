import axios from 'axios'

// Default 15s is too tight — the advisor agent runs a multi-turn tool loop
// (typically 3-6 turns, ~10-25s total). We raise the default and let long-
// running endpoints override further if needed.
const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const url = String(error.config?.url || '')
    const expectedPolicyColdStart = status === 404 && url.endsWith('/agent/trading-policy')
    if (!expectedPolicyColdStart) {
      // Keep credentials, raw request bodies and backend internals out of the browser console.
      console.error('API request failed', { status, url })
    }
    return Promise.reject(error)
  }
)

export default apiClient
