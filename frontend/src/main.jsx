import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// Marks the document so the reveal animation's hidden start state only applies where scripting can
// undo it. Without this, a failure to hydrate would leave the page blank rather than unstyled.
document.documentElement.classList.add('has-js')

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
