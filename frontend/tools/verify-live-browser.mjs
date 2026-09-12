// Run against an already-open agent-browser session. Replaces only that test page's
// microphone with synthetic audio; never records the user's microphone.
import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'

const file = process.argv[2]
if (!file) throw new Error('Usage: node tools/verify-live-browser.mjs /absolute/test.wav')
const encoded = readFileSync(file).toString('base64')
const script = `
window.__liveTest = {submitted:[], applied:[]};
window.addEventListener('signsure-sign-submitted', e => window.__liveTest.submitted.push(e.detail));
window.addEventListener('signsure-sign-applied', e => window.__liveTest.applied.push(e.detail));
navigator.mediaDevices.getUserMedia = async () => {
  const context = new AudioContext();
  await context.resume();
  const bytes = Uint8Array.from(atob(${JSON.stringify(encoded)}), c=>c.charCodeAt(0));
  const buffer = await context.decodeAudioData(bytes.buffer);
  const destination = context.createMediaStreamDestination();
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(destination);
  source.start(context.currentTime + 1);
  window.__liveTest.audioDuration = buffer.duration;
  window.__liveTest.context = context;
  return destination.stream;
};
'Synthetic microphone ready; no physical microphone will be requested.'
`
process.stdout.write(execFileSync('npx', ['--yes', 'agent-browser', '--session', 'signsure-live-check', 'eval', '--stdin'], {
  input: script, encoding: 'utf8', timeout: 30000,
}))
