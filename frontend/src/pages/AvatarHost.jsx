import { useEffect, useRef } from 'react'
import SignoraStage from '../components/SignoraStage'
import {
  finishedEvent, handleCommand, isTrustedMessageEvent, readyEvent, resolveParentOrigin, signEvent,
} from '../unity/avatarHostBridge'

/**
 * Bare host page for the Signora Unity avatar, meant to be embedded as an iframe by the
 * Chrome extension (`extension/src/avatar/unity-iframe.js`), never visited directly as a route
 * a person navigates to.
 *
 * Renders only `<SignoraStage />` full-bleed - no header, footer, or navigation - and relays the
 * `postMessage` protocol documented in `frontend/src/unity/avatarHostBridge.js` onto
 * `window.signsure`, the global `SignoraStage` already installs once the avatar calibrates. This
 * file intentionally contains no avatar logic of its own; every decision is in that tested,
 * framework-free module.
 */
export default function AvatarHost() {
  const readyRef = useRef(false)
  const trustedOriginRef = useRef(null)

  useEffect(() => {
    const trustedOrigin = resolveParentOrigin(window)
    trustedOriginRef.current = trustedOrigin

    function onMessage(event) {
      if (!isTrustedMessageEvent(event, trustedOrigin)) return
      const reply = handleCommand(event.data, window.signsure)
      if (reply) window.parent?.postMessage(reply, trustedOrigin)
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])

  return (
    <div className="avatar-host" style={{
      position: 'fixed', inset: 0, margin: 0, background: '#000',
      width: '100vw', height: '100vh', overflow: 'hidden',
    }}
    >
      <SignoraStage
        onStatus={(status) => {
          // SignoraStage reports 'calibrated:<state>' only once BeginCalibration has returned a
          // terminal, successful result - the same condition Watch.jsx and SignPage.jsx gate
          // playback on. Announce readiness exactly once, the moment that first happens.
          if (!readyRef.current && status.startsWith('calibrated:')) {
            readyRef.current = true
            window.parent?.postMessage(readyEvent(), trustedOriginRef.current)
          }
        }}
        onSignStart={(gloss, occurrenceIndex) => {
          window.parent?.postMessage(signEvent(gloss, occurrenceIndex), trustedOriginRef.current)
        }}
        onIdle={() => {
          window.parent?.postMessage(finishedEvent(), trustedOriginRef.current)
        }}
      />
    </div>
  )
}
