# Review of main.pdf against the current SignSure project

Reviewed on 7 October 2026. Source: `/Users/duveen/Downloads/main.pdf` (19 PDF pages). Page numbers below are the report's printed numbers; PDF page numbers are supplied where useful.

## Verdict and review scope

The report broadly matches the current project architecture, but it needs technical corrections and stronger implementation evidence before submission. Its English is generally clear, its equations are legible, and its restraint about linguistic validity, latency, and statistical equivalence is appropriate.

This review compared the full report with current Python, React, and Unity source, requirements, project documentation, study manifests, and selected stored analysis summaries. All 19 pages were rendered and visually inspected. No project tests, live demo, new motion analysis, rendering benchmark, or linguistic evaluation were performed. Source code establishes implementation presence, not demonstrated runtime quality. The supervisor's Review I evaluation sheet was not provided, so the attribution and exact wording of its questions cannot be independently confirmed.

The checkout HEAD was `5f4de42599598e09c93e52cfb34bccb557f94178`. Existing local changes were present, so a final report should identify both its commit and any relevant working-tree changes. The PDF and existing project files were left unchanged; this review is a separate file.

## Claims that match

| Report topic | Assessment | Current evidence |
|---|---|---|
| Combined Rokoko FBX → normalized motion → React → Unity WebGL avatar | Matches the active architecture. | `README.md`; `backend/app/services/ingest_service.py`; Unity runtime |
| Mixamo export profile, 60 fps, 100 MB upload limit | Matches the documented capture workflow and upload limit. Capture sampling rate is not proof of rendered 60 fps. | `README.md`; `backend/app/api/v1/captures.py:30` |
| Authored Start/Sign/End phases and snapped boundaries | Matches. The upload parameters specifically represent the start and end of the meaning-bearing Sign phase. | `backend/app/api/v1/captures.py:42` |
| Shared skeleton and rejection of unsafe sentence transitions | Matches. The browser also gates sentence payloads on direct blend quality. | `backend/app/services/compose_service.py`; `frontend/src/components/blendQuality.js:3` |
| Candidate previews distinguished from reviewed ISL translations | Matches the registry policy. Technical playback does not validate fluency. | `README.md`; `backend/app/services/translate_service.py` |
| Local streaming speech and prepared motion artifacts | Matches, conditional on recognizer/library readiness. | `README.md`; `backend/app/services/streaming_speech.py`; `backend/app/services/streaming_library.py` |
| YouTube URL plus uploaded subtitles, with the player controlling timing | Matches. | `README.md`; `backend/app/services/video_plan_service.py`; `frontend/src/pages/Watch.jsx` |
| FLOA with 1,000 default bootstrap draws, five trials and two performer clusters | Matches the implementation's minimum checks. Those minima do not guarantee precise or reliable population estimates. | `backend/app/validation/secondary.py:110` |
| No confirmed Fisher–Rao, ST-GCN/AGCN, or reference-versus-capture SO(3) analysis | Supported by the inspected application source. Geodesic interpolation in blending is distinct from an SO(3) evaluation module. | Application source search; `backend/app/ingest/blend.py:823` |
| Statistical equivalence not established | Matches both inspected stored summaries. | `study/action_similarity_report_v2/summary.json`; `study/matched_study/results/AFTER_intelligibility/summary.json` |

## Corrections needed

### 1. Query 1 incorrectly describes implemented smoothing as future work

**Location:** printed page 4, PDF page 6.

The response says there are no dedicated smoothing/denoising methods and proposes a One Euro filter as a future addition. Current source contradicts this:

- `backend/app/ingest/compose.py:167` applies `smooth_positions` to body and both hand tracks when preparation uses its default smoothing setting.
- `backend/app/ingest/filters.py:35` implements Savitzky–Golay position filtering.
- Both ingestion and composition call `prepare`.
- `SignoraAvatarTracking/Assets/Signora/Runtime/Tracking/TrackingFrameFilter.cs:8` configures One Euro filters for body and hands.
- `SignoraAvatarTracking/Assets/Signora/Runtime/Retargeting/SignoraAvatarDriver.cs:66` applies the tracking filter in `LateUpdate`.
- Face and bone retargeting also contain interpolation/smoothing.

Suggested replacement:

> The current pipeline includes Savitzky–Golay smoothing of body and hand landmark tracks during motion preparation, followed by skeleton enforcement. The Unity runtime applies One Euro filtering to body and hand landmarks and interpolation during retargeting. These methods are implemented, but their effect on jitter, latency, handshape preservation, and sign intelligibility has not yet been quantified in this report. Further enhancement work should begin with an ablation comparing the existing filters against unfiltered motion.

Remove the suggestion that DTW is already an online shape-correction mechanism. Current DTW aligns trajectories for comparison; alignment does not by itself correct captured motion or demonstrate improved sign quality. Any proposed playback use would need a separate algorithm and evaluation.

### 2. The workflow mixes current implementation with proposed validation

**Location:** printed page 7, PDF page 9; objective 7 on printed page 2; abstract on printed page 1.

Stages 7 and 8 sit under “The documented workflow” and read like implemented steps, even though later sections correctly say Fisher–Rao, SO(3), and the complete five-domain equivalence rule are proposed.

Keep stages 1–6 as the implemented playback workflow. Then introduce a separate paragraph:

> The implemented analysis workflow compares projected FBX motion with estimated video landmarks, reports position and angular disagreement, and provides phase-normalized, synchronization-dependent, and constrained-DTW diagnostics. A broader validation protocol using Fisher–Rao analysis, validated 3D orientation references, and uncertainty-aware all-domain equivalence testing is proposed as future work.

Change objective 7 to “Investigate suitable methods for evaluating trajectory shape, timing, disagreement, and orientation” if these are research aims rather than completed outcomes.

### 3. Table 4.1 describes only one of the current tolerance profiles

**Location:** printed pages 10–11, PDF pages 12–13.

The table correctly lists the `replication` profile, but the code now also supports `intelligibility`. It is incomplete as a description of current case-study checks.

| Domain | Replication: maximum error | Intelligibility: 95th-percentile error |
|---|---:|---:|
| Path movement | 0.05 reference shoulder widths | 0.20 reference shoulder widths |
| Arm posture | 10° | 22.5° |
| Palm-orientation proxy | 15° | 45° |
| Handshape | 0.10 hand scale | 0.25 hand scale |

Evidence: `backend/app/validation/case_study.py:34–63`, with the statistic selection at lines 94–95. The inspected AFTER output uses the `intelligibility` profile and `p95`, not the table's maximum-error rule.

Label both profiles as exploratory clip-level tolerance checks. The name “intelligibility” is a software profile name; it is not evidence that fluent signers understand the output. No empirical justification of either profile's linguistic margins was established by this review. Handshape error is normalized using a clip-level wrist-to-middle-MCP scale; state this unit explicitly instead of leaving “0.10” unexplained.

### 4. Clarify Intersection–Union failure language and code precedence

**Location:** printed page 11, PDF page 13.

The global union-null/intersection-alternative formulation is conceptually appropriate, but “one failed domain makes the overall result not equivalent” is too strong for a formal statistical test: failure to demonstrate equivalence does not necessarily demonstrate non-equivalence.

Suggested wording:

> Overall statistical equivalence is demonstrated only if every prespecified domain passes a valid equivalence test. Otherwise, equivalence is not established. Separately, the implemented exploratory certificate reports PASS or FAIL against fixed observed-error thresholds and reports INCONCLUSIVE when coverage is insufficient.

For exact code correspondence, mention that the current `intersection_union_decision` returns INCONCLUSIVE whenever any domain is inconclusive, even if another domain fails (`case_study.py:116–122`). Keep software labels separate from statistical conclusions.

### 5. Name the actual study output instead of saying “the current case study”

**Location:** printed page 14, PDF page 16.

The report describes one case with provisional review and unresolved synchronization. That describes the ACTION configuration, but multiple outputs are present:

- ACTION's current manifest declares `separate_repetitions`. Its stored similarity output explicitly says these differences cannot establish capture accuracy, superiority, or equivalence. The report should state this directly, not merely say synchronization is unresolved.
- A separate stored AFTER output declares `same_performance`, uses an `intelligibility` profile, and contains both phase-normalized and synchronized analyses. That declaration is recorded provenance, not an independent verification by this review.

Identify the chosen action, exact manifest/output path, generation date, recording relationship, camera assumption, alignment, and tolerance profile. Do not mix historical outputs or present old outputs as a fresh run of today's implementation.

### 6. Chapter 5 needs concrete results or a more accurate title

**Location:** printed pages 14–15, PDF pages 16–17.

The status table is useful but is an implementation inventory, not an experimental results section. Add actual evidence available for the review: interface screenshots, a successful prepared example, vocabulary and capture counts measured for the named snapshot, archived test results, and a clearly labelled descriptive analysis table/plot. Include negative or inconclusive findings. Do not invent performance numbers.

If no experiments are ready, rename the chapter “Implementation Status and Evaluation Plan.” It is acceptable for Review II to contain preliminary results, provided they are identified as such.

The report underrepresents existing research tools while devoting substantial space to unimplemented ones. Consider adding the paired mixed-effects model for a qualified matched study, constrained DTW, SPM1D, and action-shape diagnostics as implemented capabilities with their data requirements. Their presence is not evidence that a population study has been completed. Relevant files: `validation/mixed_effects.py`, `validation/secondary.py`, and `validation/action_shape.py`.

### 7. Update technology and naming details

**Location:** printed pages 8–9 and 12–13; cover and bibliography.

- The repository is called **SignSure**, while the avatar/Unity project is **Signora**. The report title can remain Signora, but define the relationship once: “SignSure is the application, using the Signora avatar and Unity runtime.”
- Add **DWPose via rtmlib and ONNX Runtime** to the analysis technology description. This is the current extraction implementation (`backend/app/validation/video_pose.py:81–96`), although portions of `backend/VALIDATION.md` still describe an older MediaPipe setup. Prefer source evidence over stale documentation.
- Replace “Start and End timestamps” with “the start and end timestamps of the meaning-bearing Sign phase.” The existing sentence is broadly consistent with the API's embedded-boundary exception, but the terminology is ambiguous.
- Keep the distinction between 60-fps sampling, playback speed, rendering frame rate, and end-to-end latency. Query 4's caution is appropriate; 60 fps does not establish any latency target.

## Writing, references, and presentation

### Writing

The prose is generally grammatical and restrained. Its main weakness is repeated audit language such as “the inspected repository snapshot,” “documented status,” and “not confirmed.” State the evidence scope once, then describe implemented behavior directly. Retain limitations where they materially affect interpretation.

- Replace “Draft response” with “Response” in a final submission.
- Change “First Review - Queries and Answers” to “Review I: Questions and Responses,” if permitted by the college format.
- Change “Rendering of the Avatar – efficiency” to “How efficient is avatar rendering?”
- Explain new abbreviations at first use: FBX, FLOA, SO(3), ST-GCN, and AGCN.
- If discussing ST-GCN/AGCN, describe them primarily as action-recognition models. Their ability to enhance motion would require a specifically designed and evaluated additional method.
- Add primary citations for the conceptual answers about [ST-GCN](https://arxiv.org/abs/1801.07455) and [2s-AGCN](https://arxiv.org/abs/1805.07694). The report correctly treats them as unimplemented concepts.
- If calling the method “Fisher–Rao trajectory comparison,” specify the trajectory representation, distance, warping constraints, and how normalized phase variation will be separated from physical duration when the method is eventually implemented. The cited [Fisher–Rao paper](https://arxiv.org/abs/1103.3817) supports amplitude/phase separation; it does not supply a completed SignSure evaluation.

### References

1. **Reference [5] has the wrong second author.** Use **H. Dette and K. Kokot**, not “H. Dette and W. W. Dette.” Title, journal, year, pages, and DOI correspond to the [Oxford journal record](https://academic.oup.com/biomet/issue/108/4?browseBy=volume).
2. **Reference [1] misspells Patrick Boudreault.** The [authors' paper](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/07/Sign_Language_Workshop_accessible.pdf) gives “Boudreault.” The Microsoft landing-page metadata also contains the typo, so use the paper's author list.
3. Reference [4] supports the conventional mean ± 1.96 SD limits of agreement. Explain that the action-indexed curves and performer-cluster bootstrap are the project's extension, and state distribution/dependence assumptions rather than implying that this one citation validates the entire implementation. See the [original article record](https://pubmed.ncbi.nlm.nih.gov/10501650/).
4. Make reference [7] reproducible: repository name/URL if available, commit ID, inspection date, relevant paths, and relevant local changes. Do not supply an invented URL.

The SO(3) matrix and unit-quaternion formulas are mathematically correct for valid rotations and normalized quaternions. The warning about an insufficient monocular 2D orientation reference is appropriate. The citation corresponds to [Huynh's rotation-metrics paper](https://research-repository.uwa.edu.au/en/publications/metrics-for-3d-rotations-comparison-and-analysis/).

### Visual layout

No obvious clipped text, overlapping equations, broken glyphs, or overflowing tables were visible in the rendered pages. Apparent joined words in PDF extraction generally render with normal spacing; do not treat those extraction artifacts as confirmed typesetting defects.

The layout is usable but can be improved:

- Printed page 3 contains only the short Scope section; move it onto the preceding introduction page if the template permits.
- The abstract has substantial unused space and spends much of its limited text listing unimplemented validation methods. Focus it on the implemented contribution, evaluation status, and central limitation.
- Figure 4.1 is small and its labels wrap heavily. Enlarge it and label the motion-JSON return path to React and frame stream to Unity.
- Add the bibliography to the table of contents. Add lists of figures and tables only if required by the college template.
- Remove periods inside student-ID parentheses. Format the supervisor's name as “Dr. B. Prabavathy,” unless a prescribed institutional style requires otherwise.

## Suggested revised abstract

> SignSure is a browser-based prototype that presents recorded Indian Sign Language motion through the Signora avatar. A FastAPI backend ingests combined Rokoko FBX captures, normalizes body, hand, and facial channels, and composes motion using authored Start, Sign, and End phases with transition-quality checks. A React interface streams motion to a calibrated Unity WebGL runtime. Supported text is resolved through a versioned pattern registry that distinguishes reviewed translations from candidate literal previews. Optional workflows support local microphone recognition and subtitle-driven playback. The project also includes video–FBX comparison tools that report projected motion disagreement and preserve recording provenance. Existing case-study outputs are descriptive and do not establish statistical equivalence, capture-method superiority, or linguistic intelligibility. Fisher–Rao analysis, reference-based SO(3) orientation evaluation, and a complete statistical all-domain equivalence protocol remain proposed extensions.

## Submission priorities

First correct Query 1, distinguish proposed workflow steps, document both tolerance profiles, fix reference [5], and identify the exact study output. Then strengthen Chapter 5 with archived evidence, update the naming/technology details, and polish the layout and final-submission wording.
