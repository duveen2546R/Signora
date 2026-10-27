import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
import json

def calculate_velocity(df: pd.DataFrame, joint_x: str, joint_y: str) -> np.ndarray:
    """Calculates the 2D velocity magnitude of a joint over time."""
    # Compute differences between consecutive frames
    dx = df[joint_x].diff()
    dy = df[joint_y].diff()
    
    # Calculate magnitude of the velocity vector
    velocity = np.sqrt(dx**2 + dy**2)
    # Fill the first NaN value with 0
    return velocity.fillna(0).to_numpy()

def annotate_directory(directory: Path):
    pose_file = directory / "reference_pose.csv"
    if not pose_file.exists():
        print(f"Error: {pose_file} not found. Run the video ingestion first.")
        return

    print(f"Loading {pose_file}...")
    df = pd.read_csv(pose_file)
    
    # Check if we have standard DWPose wrist columns
    # Assuming columns like 'right_wrist_x', 'right_wrist_y' exist
    # Adjust these column names based on your actual reference_pose.csv format
    right_wrist_x, right_wrist_y = 'right_wrist_x', 'right_wrist_y'
    
    if right_wrist_x not in df.columns:
        print(f"Columns not found. Available columns: {list(df.columns)}")
        print("Using the first available X and Y coordinates as a fallback...")
        # Fallback to the first x/y columns if standard naming isn't used
        x_cols = [c for c in df.columns if c.endswith('_x')]
        y_cols = [c for c in df.columns if c.endswith('_y')]
        if not x_cols:
            return
        right_wrist_x, right_wrist_y = x_cols[0], y_cols[0]

    velocity = calculate_velocity(df, right_wrist_x, right_wrist_y)
    frames = np.arange(len(velocity))

    # Set up interactive plot
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(frames, velocity, label="Wrist Velocity", color="blue")
    ax.set_title(f"Click the 'Stroke Apex' (Minimum Velocity during the sign)\nDirectory: {directory.name}")
    ax.set_xlabel("Frame Number")
    ax.set_ylabel("Velocity (Pixels/Frame)")
    ax.grid(True)
    
    annotations = []

    def onclick(event):
        if event.xdata is not None:
            frame = int(round(event.xdata))
            vel = event.ydata
            print(f"Annotated Apex at Frame: {frame}")
            
            # Draw a red dot where the user clicked
            ax.plot(frame, vel, 'ro')
            fig.canvas.draw()
            
            annotations.append(frame)

    cid = fig.canvas.mpl_connect('button_press_event', onclick)
    
    print("Close the plot window when you are finished.")
    plt.show()

    if annotations:
        # Save the first click as the anchor
        anchor_frame = annotations[0]
        output_data = {
            "stroke_apex_frame": anchor_frame,
            "total_frames": len(frames)
        }
        
        output_file = directory / "temporal_anchor.json"
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=4)
        print(f"Successfully saved temporal anchor to {output_file}")
    else:
        print("No annotations made.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python annotate_temporal.py <path_to_case_study_directory>")
        sys.exit(1)
        
    target_dir = Path(sys.argv[1]).resolve()
    annotate_directory(target_dir)
