"""Private native FBX worker; never import native wrappers into the CLI process."""

import os
import sys
import numpy as np

from .fbx_motion import _load_native

if __name__ == "__main__":
    try:
        motion = _load_native(
            sys.argv[1],
            include_elbows=sys.argv[3] == "elbows",
            include_extras=sys.argv[3] == "extras",
        )
        np.savez(
            sys.argv[2],
            profile=motion.profile,
            fps=motion.fps,
            times=motion.times,
            joints=motion.joints,
            **({"extras": motion.extras} if motion.extras is not None else {}),
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        os._exit(2)
    sys.stdout.flush()
    os._exit(0)
