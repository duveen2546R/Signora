# SignSure frontend

React/Vite studio for FBX capture review, avatar signing, live speech, and YouTube subtitles.

```bash
npm install
npm run dev
```

Run the FastAPI backend on port 8000 in a separate terminal, then open
[http://localhost:5173](http://localhost:5173). See the [project README](../README.md)
for setup and the Mixamo FBX export requirements.

The Capture page supports multiple FBX selections, per-file timestamp review, and
**Upload all ready captures**. The browser streams normalized motion to the active
`SignoraAvatarTracking` Unity WebGL runtime.

```bash
npm test
npm run lint
npm run build
```
