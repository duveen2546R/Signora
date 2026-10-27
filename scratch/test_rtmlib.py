import cv2
import numpy as np
from rtmlib import Wholebody

def test_rtmlib():
    print("Initializing Wholebody...")
    wholebody = Wholebody(
        mode='performance',
        to_openpose=False,
        backend='onnxruntime',
        device='cpu'
    )
    print("Created.")
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    print("Running inference...")
    keypoints, scores = wholebody(img)
    print("Shape:", keypoints.shape if len(keypoints) else "No person detected")
    print("Done")

if __name__ == '__main__':
    test_rtmlib()
