import argparse
import sys
from pathlib import Path
import numpy as np
from scipy import signal

# Add backend to path so we can import app modules
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.validation.video_pose import read_pose_csv as load_pose
from app.validation.fbx_motion import load_motion

def compute_speed(times, points):
    # points: (frames, joints, coords)
    # calculate delta time
    dt = np.diff(times)
    # calculate distance traveled by joints between frames
    # we'll just use wrists (indices 4 and 5)
    wrists = points[:, 4:6, :2] # only use x,y for speed correlation to be safe across 2D/3D
    dp = np.diff(wrists, axis=0)
    # magnitude of velocity
    speed = np.linalg.norm(dp, axis=2) # shape: (frames-1, 2)
    # average speed of both wrists
    avg_speed = speed.mean(axis=1)
    
    # handle 0 dt or NaNs safely
    valid = dt > 0
    dt_safe = np.where(valid, dt, 1.0)
    velocities = np.zeros_like(avg_speed)
    velocities[valid] = avg_speed[valid] / dt_safe[valid]
    
    # times for velocities (midpoints)
    v_times = times[:-1] + dt / 2
    
    # smooth the velocity slightly to help correlation overlap
    if len(velocities) > 5:
        velocities = signal.savgol_filter(velocities, window_length=5, polyorder=2)
        
    return v_times, np.clip(velocities, 0, None)

def auto_sync(video_path, fbx_path):
    print(f"Loading video pose from {video_path}...")
    pose = load_pose(video_path)
    
    print(f"Loading Rokoko FBX from {fbx_path}...")
    motion = load_motion(fbx_path)
    
    # 1. Compute Hand Speeds
    print("Computing hand velocities...")
    v_times_vid, v_speed_vid = compute_speed(pose.times, pose.xy)
    v_times_fbx, v_speed_fbx = compute_speed(motion.times, motion.joints)
    
    # Normalize speeds so their peaks are comparable
    v_speed_vid = v_speed_vid / (np.max(v_speed_vid) + 1e-6)
    v_speed_fbx = v_speed_fbx / (np.max(v_speed_fbx) + 1e-6)
    
    # 2. Resample to a common framerate (60 fps)
    fps = 60.0
    common_dt = 1.0 / fps
    
    max_time = max(v_times_vid[-1], v_times_fbx[-1])
    common_times = np.arange(0, max_time, common_dt)
    
    # Interpolate both to the common time base
    sig_vid = np.interp(common_times, v_times_vid, v_speed_vid, left=0, right=0)
    sig_fbx = np.interp(common_times, v_times_fbx, v_speed_fbx, left=0, right=0)
    
    # 3. Cross-correlation
    print("Running cross-correlation to find optimal time shift...")
    correlation = signal.correlate(sig_vid, sig_fbx, mode='full')
    lags = signal.correlation_lags(len(sig_vid), len(sig_fbx), mode='full')
    
    best_lag_index = np.argmax(correlation)
    best_lag = lags[best_lag_index]
    
    time_offset = best_lag * common_dt
    
    print("\n" + "="*50)
    print("✅ AUTO-SYNC COMPLETE")
    print("="*50)
    if time_offset > 0:
        print(f"The Rokoko recording started AFTER the video.")
        print(f"The exact offset is: {time_offset:.3f} seconds.")
        print(f"-> If the video action starts at  t = 2.000s")
        print(f"-> The Rokoko action starts at  t = {(2.000 - time_offset):.3f}s")
    else:
        print(f"The Rokoko recording started BEFORE the video.")
        print(f"The exact offset is: {abs(time_offset):.3f} seconds.")
        print(f"-> If the video action starts at  t = 2.000s")
        print(f"-> The Rokoko action starts at  t = {(2.000 + abs(time_offset)):.3f}s")
    
    print("\nUse this offset to perfectly align your action windows!")
    print("="*50)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video", help="Path to the video file or .csv landmarks")
    parser.add_argument("fbx", help="Path to the Rokoko FBX file")
    args = parser.parse_args()
    
    auto_sync(args.video, args.fbx)
