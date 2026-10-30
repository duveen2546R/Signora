"""Exploratory variants for the Action take (not the pre-registered protocol).

usage: action_variant.py {no_offset|post_hold} OUTPUT
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "/Users/duveen/Projects/SignSure/backend")
from app.validation import conditional_equivalence as ce
from app.validation import multiview as mv
from app.validation.single_take_job import run_single_take

variant, output = sys.argv[1], Path(sys.argv[2])
root = Path("/Users/duveen/Projects/SignSure/validationDataset/Action")

if variant == "no_offset":
    ce.offset_rule = lambda path=None: None
elif variant == "post_hold":
    def post_hold(motion, onset):
        _, stop = mv.sign_window(motion)
        start = stop + int(round(mv.REST_GAP_S * motion.fps))
        end = min(len(motion.times), start + int(round(0.8 * motion.fps)))
        if end - start < int(round(mv.REST_MIN_S * motion.fps)):
            raise ce.ValidationError("post-sign hold too short")
        return slice(start, end)
    ce.rest_window = post_hold
else:
    raise SystemExit(f"unknown variant {variant}")

output.mkdir(parents=True, exist_ok=True)
cache = root / "results" / "pose-cache"
if cache.exists() and not (output / "pose-cache").exists():
    shutil.copytree(cache, output / "pose-cache")
report = run_single_take(
    root / "Action--Front.mp4", root / "Action-Side.mp4", root / "Action_1_mixamo.fbx", output,
    progress=lambda message: None, refine_focal=__import__("os").environ.get("FIXED") != "1",
)
print(variant, report["decision"], report["diagnostics"]["window_s"], report["diagnostics"].get("rest_window_s"))
print("lags", report["diagnostics"]["view_lag_s"], report["diagnostics"]["fbx_lag_s"])
for name, item in report["angles"].items():
    print(f"{name:26s} {item['decision']:16s} rms {item['rms_deg']:5.1f} up {item['rms_ci_deg'][1]:5.1f} "
          f"raw {item['raw_rms_deg']:5.1f} off {item['static_offset_deg']:+6.1f} rep {item['replicate_check']['pass']}")
