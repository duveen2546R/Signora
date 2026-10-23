SignSure - Setup and Execution Guide
=====================================

SignSure converts English text into an Indian Sign Language (ISL) motion preview. A React/Vite
web application streams normalized motion to a Unity WebGL avatar, while a FastAPI backend
processes motion captures, manages the sign library, and serves the API.


1. DATASET / SOURCE
-------------------

This project does not use a third-party downloadable sign-language dataset. Its motion dataset is
made from locally recorded Rokoko Studio motion-capture exports:

* Included raw capture files: MotionCaptureFbx/*.fbx (51 Mixamo-rig FBX files).
* Capture source: Rokoko Studio, https://www.rokoko.com/products/studio
* Rig/export format: a combined FBX containing body, Smartglove, and 52 ARKit facial channels;
  export using the Mixamo skeleton at 60 fps.
* Repository source: https://github.com/duveen2546R/Signora

The FBX files are example/source captures; they are not automatically registered in the application's
library. To use a capture, start the application and upload it through the Capture page. The backend
stores imported source files, normalized motion, and its SQLite database under backend/data/.
Those local runtime files are intentionally ignored by Git, so create/import the required sign library
on each fresh setup. The bundled ISL phrase patterns are review candidates and must be reviewed by a
fluent ISL signer before being represented as approved translations.


2. SOFTWARE REQUIREMENTS
------------------------

Required to run the web application:

* Operating system: macOS, Linux, or Windows with a Bash-compatible terminal (commands below use
  macOS/Linux paths; on Windows use the equivalent virtual-environment commands).
* Python: 3.11 or newer.
* Node.js: 20.19+ or 22.12+, including npm.
* A modern WebGL 2-capable browser such as current Chrome, Edge, or Firefox.

Required only to rebuild or edit the avatar:

* Unity 6000.5.9f1 with the WebGL Build Support module.

Optional features:

* Video/FBX validation: Python packages in backend/requirements-validation-video.txt. These include
  RTMLib and ONNX Runtime; DWPose model weights download on first use.
* Local microphone signing: packages in backend/requirements-live.txt, followed by the speech-model
  setup command shown below. The initial model download is approximately 44 MB extracted.


3. HARDWARE REQUIREMENTS
------------------------

* Development/runtime: a 64-bit computer with at least 8 GB RAM, a stable internet connection for
  first-time package/model downloads, and a GPU/browser driver capable of WebGL 2. 16 GB RAM is
  recommended when running Unity or video validation.
* Audio signing (optional): a microphone and browser permission to access it.
* Creating new motion captures (optional): a Rokoko-compatible motion-capture setup with body,
  Smartglove, and facial capture capability. Existing FBX files can be used without this hardware.


4. INSTALLATION AND EXECUTION
-----------------------------

Open two terminals at the repository root. The backend must run on port 8000 while the frontend
development server runs on port 5173.

4.1 Obtain the source code

    git clone https://github.com/duveen2546R/Signora.git SignSure
    cd SignSure

If the project has already been supplied locally, simply change into its root directory instead.

4.2 Create the Python environment and install backend dependencies

    cd backend
    python3 -m venv .venv
    ./.venv/bin/python -m pip install --upgrade pip
    ./.venv/bin/pip install -r requirements-dev.txt

Install the video/FBX validation dependencies only if the Analysis workflow will be used:

    ./.venv/bin/pip install -r requirements-validation-video.txt

4.3 Start the backend (terminal 1)

From the backend directory:

    ./.venv/bin/uvicorn app.main:app --reload --port 8000

Leave this terminal running. The API is then available at http://localhost:8000.

4.4 Install and start the frontend (terminal 2)

From the repository root:

    cd frontend
    npm install
    npm run dev

Open http://localhost:5173 in a WebGL-capable browser. Vite automatically proxies /api requests to
the backend at port 8000. If the backend is hosted elsewhere, set VITE_API_BASE to its URL before
starting Vite.

4.5 Load a sample or new motion capture

1. In the web application, open Capture.
2. Select one or more FBX files from MotionCaptureFbx/ (or a new compatible Rokoko export).
3. For every file, provide the sign-start and sign-end timestamps displayed by the capture editor.
4. Select Upload capture, or Upload all ready captures for a batch.
5. After the avatar reports calibrated:complete, preview an uploaded sign or enter a supported
   sentence in the Studio.

Files should be exported from Rokoko Studio as a combined FBX at 60 fps using the Mixamo skeleton.
Keep "Use Clip start time as time zero" enabled, and disable "Include reference pose" and
"Extract root motion". One sign should be stored in each FBX file.

4.6 Optional: enable local microphone signing

In backend/, using the same Python environment that runs uvicorn:

    ./.venv/bin/python -m pip install -r requirements-live.txt
    ./.venv/bin/python tools/setup_live_speech.py
    ./.venv/bin/python tools/compile_live_library.py --streaming

Restart the backend after installation. In the Studio, wait for avatar calibration, choose Warm local
recognizer, then choose Start listening and allow microphone access.

4.7 Optional: rebuild the Unity WebGL avatar

1. Open SignoraAvatarTracking/ in Unity 6000.5.9f1.
2. Install any packages Unity requests, including WebGL Build Support.
3. Select Signora > Build WebGL.
4. Verify that SignoraAvatarTracking/WebBuild/Build/WebBuild.wasm exists.
5. Restart or reload the frontend.

The frontend's public/unity path points to this WebBuild directory, so no manual copy is needed.


5. VERIFY THE INSTALLATION
--------------------------

Run the automated checks from the repository root after dependencies are installed:

    cd backend && ./.venv/bin/python -m pytest -q
    cd ../frontend && npm test && npm run lint && npm run build

The application is ready when the frontend loads at http://localhost:5173, the backend remains
reachable at http://localhost:8000, and the avatar status shows calibrated:complete.
