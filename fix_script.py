import sys
from app.validation.fbx_motion import load_motion
motion = load_motion("study/matched_study/data/AFTER/motioncapture.fbx", include_elbows=True)
print(dir(motion))
