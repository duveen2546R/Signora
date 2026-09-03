const BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, options)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? detail
    } catch {
      // Non-JSON error body; the status text is the best we have.
    }
    throw new Error(detail)
  }
  return response.status === 204 ? null : response.json()
}

export const api = {
  health: () => request('/health'),

  listSigns: ({ q = '', limit = 200 } = {}) =>
    request(`/signs?limit=${limit}${q ? `&q=${encodeURIComponent(q)}` : ''}`),

  setCanonical: (clipId) => request(`/signs/${clipId}/canonical`, { method: 'POST' }),

  translate: (text) =>
    request('/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }),

  listRigs: () => request('/rigs'),

  // The avatar's bind pose, used as the retargeting reference.
  calibration: () => request('/rigs/calibration'),

  uploadRig: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/rigs', { method: 'POST', body: form })
  },

  uploadCapture: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/captures', { method: 'POST', body: form })
  },

  captureStatus: (jobId) => request(`/captures/${jobId}`),

  // Landmark frames for the Signora Unity runtime, which retargets in-engine.
  landmarks: (url) => request(url.replace('/api/v1', '')),
}

export const clipUrl = (contentPath) => `${BASE.replace('/api/v1', '')}${contentPath}`
