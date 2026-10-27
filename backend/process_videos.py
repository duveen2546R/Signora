import sys
from pathlib import Path
from app.validation.video_pose import extract_video_pose
from app.core.config import settings

video_dir = Path("videos")
videos = list(video_dir.glob("*.mp4"))

for video_path in videos:
    print(f"Processing {video_path.name}...")
    
    # We create a specific analysis directory for each video to keep outputs organized
    output_dir = Path("study") / "matched_study" / "data" / video_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # We copy the video there as reference.mp4 to match the expected format
    ref_vid_path = output_dir / "reference.mp4"
    if not ref_vid_path.exists():
        ref_vid_path.write_bytes(video_path.read_bytes())
        
    csv_out = output_dir / "reference_pose.csv"
    if not csv_out.exists():
        try:
            # Assuming settings.analysis_pose_model and hand_model are correctly set in the environment
            extract_video_pose(
                ref_vid_path,
                settings.analysis_pose_model,
                csv_out,
                include_elbows=True,
                hand_model=settings.analysis_hand_model
            )
            print(f"Successfully extracted pose to {csv_out}")
        except Exception as e:
            print(f"Failed extracting pose for {video_path.name}: {e}")
    else:
        print(f"Pose already extracted for {video_path.name}")
        
print("All videos processed.")
