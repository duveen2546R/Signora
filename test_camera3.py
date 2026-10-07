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

# Facing FORWARD (+Z). Left is +X.
xyz_f = np.zeros((1, 8, 3))
xyz_f[0, 0] = [1, 0, 0]
xyz_f[0, 1] = [-1, 0, 0]
xyz_f[0, 2] = [0.8, -3, 0]
xyz_f[0, 3] = [-0.8, -3, 0]
xyz_f[0, 6] = [1.2, -1.5, 2] # Elbow points +Z

# Facing BACKWARD (-Z). Left is -X.
xyz_b = np.zeros((1, 8, 3))
xyz_b[0, 0] = [-1, 0, 0]
xyz_b[0, 1] = [1, 0, 0]
xyz_b[0, 2] = [-0.8, -3, 0]
xyz_b[0, 3] = [0.8, -3, 0]
xyz_b[0, 6] = [-1.2, -1.5, -2] # Elbow points -Z (because rotated 180 around Y)

reference = np.zeros((1, 8, 2))
# Video reference where person faces camera (-Z) so elbows point -Z.
# But in 2D video, we don't have Z!
# If person faces camera, and elbows point -Z, it's foreshortened.
reference[0, 0] = [1, 0]
reference[0, 1] = [-1, 0]
reference[0, 2] = [0.8, 4]
reference[0, 3] = [-0.8, 4]
reference[0, 6] = [1.2, 2]

res_f = camera_fits(xyz_f, reference, np.array([True]))[0]
res_b = camera_fits(xyz_b, reference, np.array([True]))[0]

for name, res, xyz in [("Forward", res_f, xyz_f), ("Backward", res_b, xyz_b)]:
    p_vec = (xyz[0, 6] @ res["r"].T)[:2] - (xyz[0, 0] @ res["r"].T)[:2]
    r_vec = reference[0, 6] - reference[0, 0]
    angle = np.degrees(np.arccos(np.clip(np.sum(p_vec * r_vec) / (np.linalg.norm(p_vec)*np.linalg.norm(r_vec)), -1, 1)))
    print(name, "Angle:", angle)

