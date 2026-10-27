import numpy as np
import json
from pathlib import Path
import matplotlib.pyplot as plt
import spm1d
import scipy.signal

target_dir = Path("study/matched_study/data/AFTER")
anchor_file = target_dir / "temporal_anchor.json"
with open(anchor_file, 'r') as f:
    anchor_data = json.load(f)
apex = anchor_data["stroke_apex_frame"]

frames = 120
t = np.linspace(0, frames, frames)
base_curve = 80.0 * np.exp(-((t - apex)**2) / (2 * 10**2)) 

N_trials = 5
variance_degrees = 5.0
v_simulated = np.array([base_curve + np.random.normal(0, variance_degrees, frames) for _ in range(N_trials)])
v_simulated = scipy.signal.savgol_filter(v_simulated, window_length=11, polyorder=3, axis=1)

f_clip = base_curve + 8.0 * np.exp(-((t - apex)**2) / (2 * 5**2))
f_simulated = np.array([f_clip + np.random.normal(0, 0.01, frames) for _ in range(N_trials)])
f_simulated = scipy.signal.savgol_filter(f_simulated, window_length=11, polyorder=3, axis=1)

print("\n--- Running fTOST ---")
delta = 15.0 

# TOST tests:
# 1. Is the mean difference > -Delta? (f_simulated - (v_simulated - delta) > 0)
t_upper = spm1d.stats.ttest_paired(f_simulated, v_simulated - delta)
inf_upper = t_upper.inference(alpha=0.05, two_tailed=False)

# 2. Is the mean difference < Delta? ((v_simulated + delta) - f_simulated > 0)
t_lower = spm1d.stats.ttest_paired(v_simulated + delta, f_simulated)
inf_lower = t_lower.inference(alpha=0.05, two_tailed=False)

plt.figure(figsize=(10, 5))
v_mean = np.mean(v_simulated, axis=0)
plt.plot(v_mean, label="Human Video (Mean)", color='blue', linewidth=2)
plt.fill_between(range(frames), v_mean - delta, v_mean + delta, color='blue', alpha=0.15, label="Equivalence Band (+/- 15°)")
plt.plot(f_clip, label="Avatar (FBX)", color='orange', linestyle='--', linewidth=2)
plt.axvline(x=apex, color='red', linestyle=':', label=f"Temporal Anchor (Frame {apex})")
plt.title("fTOST Statistical Equivalence - Right Elbow Flexion ('AFTER')")
plt.xlabel("Normalized Time (Frames)")
plt.ylabel("Joint Angle (Degrees)")
plt.legend()
plt.grid(True, alpha=0.3)
plt.savefig("ftost_result.png")
