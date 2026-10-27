import numpy as np
import math
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

def camera_fits(xyz, reference, calibration_mask):
    valid = calibration_mask
    def residual(parameters):
        r = Rotation.from_rotvec(parameters[:3]).as_matrix()
        return (
            (xyz[valid, :4] @ r.T)[..., :2] * np.exp(parameters[3])
            - reference[valid, :4]
        ).ravel()
    starts = (
        [0, 0, 0], [np.pi, 0, 0], [0, np.pi, 0], [0, np.pi / 2, 0],
        [0, -np.pi / 2, 0], [np.pi, np.pi / 2, 0], [np.pi - 0.6, 0, 0],
        [np.pi + 0.6, 0, 0], [np.pi, 0.6, 0], [np.pi, -0.6, 0]
    )
    results = []
    for angles in starts:
        solution = least_squares(
            residual, [*angles, 0.0], max_nfev=600,
            bounds=([-2 * np.pi] * 3 + [math.log(0.35)], [2 * np.pi] * 3 + [math.log(2.5)])
        )
        rmse = float(np.sqrt(np.mean(solution.fun**2)))
        if solution.success:
            results.append({"rot": solution.x[:3], "rmse": rmse, "r": Rotation.from_rotvec(solution.x[:3]).as_matrix()})
    results.sort(key=lambda x: x["rmse"])
    return results

xyz = np.zeros((1, 8, 3))
# Shoulders at Y=0, Hips at Y=-3
xyz[0, 0] = [1, 0, 0]  # L shoulder
xyz[0, 1] = [-1, 0, 0] # R shoulder
xyz[0, 2] = [0.8, -3, 0] # L hip
xyz[0, 3] = [-0.8, -3, 0] # R hip
xyz[0, 6] = [1.2, -1.5, 0] # L elbow
reference = np.zeros((1, 8, 2))
# Shoulders at Y=0, Hips at Y=4
reference[0, 0] = [1, 0]
reference[0, 1] = [-1, 0]
reference[0, 2] = [0.8, 4]
reference[0, 3] = [-0.8, 4]
reference[0, 6] = [1.2, 2]

res = camera_fits(xyz, reference, np.array([True]))
best = res[0]
print("Best RMSE:", best["rmse"])
print("Best Rot Matrix:\n", best["r"])
print("Projected L Elbow:\n", (xyz[0, 6] @ best["r"].T)[:2])
print("Reference L Elbow:\n", reference[0, 6])
