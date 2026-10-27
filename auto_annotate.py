import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import json
import scipy.signal

def calculate_velocity(df: pd.DataFrame, joint_x: str, joint_y: str) -> np.ndarray:
    dx = df[joint_x].diff()
    dy = df[joint_y].diff()
    velocity = np.sqrt(dx**2 + dy**2)
    # Apply a slight smoothing filter to reduce camera jitter
    smooth_vel = scipy.signal.savgol_filter(velocity.fillna(0).to_numpy(), window_length=5, polyorder=2)
    return smooth_vel

target_dir = Path("study/matched_study/data/AFTER")
pose_file = target_dir / "reference_pose.csv"

print(f"Loading {pose_file}...")
df = pd.read_csv(pose_file)

# Standard DWPose wrist columns
right_wrist_x, right_wrist_y = 'right_wrist_x', 'right_wrist_y'
if right_wrist_x not in df.columns:
    right_wrist_x, right_wrist_y = [c for c in df.columns if c.endswith('_x')][0], [c for c in df.columns if c.endswith('_y')][0]

velocity = calculate_velocity(df, right_wrist_x, right_wrist_y)

# Find the valley (minimum velocity) in the middle 60% of the sign to avoid the start/end resting positions
start_idx = int(len(velocity) * 0.2)
end_idx = int(len(velocity) * 0.8)

middle_velocity = velocity[start_idx:end_idx]
# Find the frame with the absolute minimum velocity in this middle section (the "stroke hold")
relative_apex = np.argmin(middle_velocity)
absolute_apex = start_idx + relative_apex

print(f"Auto-detected Stroke Apex at Frame: {absolute_apex}")

# Save the JSON
output_data = {
    "stroke_apex_frame": int(absolute_apex),
    "total_frames": len(velocity),
    "auto_detected": True
}
output_file = target_dir / "temporal_anchor.json"
with open(output_file, 'w') as f:
    json.dump(output_data, f, indent=4)

# Create a plot and save it as an image so the user can verify
plt.figure(figsize=(10, 5))
plt.plot(np.arange(len(velocity)), velocity, label="Wrist Velocity", color="blue")
plt.plot(absolute_apex, velocity[absolute_apex], 'ro', markersize=10, label="Detected Apex")
plt.axvspan(0, start_idx, color='gray', alpha=0.2, label="Ignored (Start/End)")
plt.axvspan(end_idx, len(velocity), color='gray', alpha=0.2)
plt.title("Auto-Detected Stroke Apex for 'AFTER' Sign")
plt.xlabel("Frame Number")
plt.ylabel("Smoothed Velocity")
plt.legend()
plt.grid(True)
plot_path = target_dir / "apex_plot.png"
plt.savefig(plot_path)
print(f"Saved visualization to {plot_path}")
