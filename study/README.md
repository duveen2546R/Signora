# ACTION video–FBX case study

`trials_torsofree.json` is the current reproducible case configuration. On 2026-10-05 the user
clarified that the sources are **separate repetitions**, correcting the earlier same-performance
assumption. These data cannot establish capture accuracy or superiority. The eight-joint video
reference and its extraction metadata are in `landmarks/`.
`action_similarity_report_v2/report.html` is the current descriptive report;
`summary.json` and CSV traces hold its measurements and provenance.

The `action_similarity_report`, `action_case_report`, `scores_prev`, `scores_wristonly`, `scores_v2_wristelbow`, and `scores_v3` directories are
historical outputs. Their recorded input hashes differ from the current regenerated reference;
they have not been relabelled or overwritten. Their earlier same-performance interpretation has
been superseded by the user's clarification. The matched-study scorer now rejects this manifest;
use the `case-study` command for movement similarity.

See [the case-study protocol](../backend/VALIDATION.md#single-performance-case-study) for commands,
configuration, units, synchronization requirements, and interpretation. Recording speed, source
windows, and camera calibration remain unresolved. Statistical equivalence is not established.
