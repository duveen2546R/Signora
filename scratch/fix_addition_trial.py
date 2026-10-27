import sys
import json
from pathlib import Path
sys.path.append('backend')
from app.validation.video_pose import extract_video_pose
from app.validation.trials import sha256

def fix_addition_trial():
    manifest_path = Path('study/matched_study/manifest_addition.json')
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
        
    trial = manifest['trials'][0]
    
    # Path relative to manifest
    base_dir = manifest_path.parent
    video_path = base_dir / trial['reference_video']
    pose_csv = base_dir / trial['video_landmarks']
    
    print(f"Extracting DWPose for {video_path} -> {pose_csv}")
    
    # Needs to output to the correct path
    meta = extract_video_pose(
        video=video_path,
        model='dummy', # not used anymore
        output=pose_csv,
        include_elbows=True
    )
    
    print("Updating manifest hashes...")
    trial['sha256']['video_landmarks'] = meta['landmarks_sha256']
    manifest['case_study']['video_metadata_sha256'] = sha256(pose_csv.with_suffix('.metadata.json'))
    
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
        
    print("Done!")

if __name__ == '__main__':
    fix_addition_trial()
