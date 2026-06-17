"""
cv_engine_base.py — Interface contract for all CV engine implementations.

Both the simulator (CVEngineSimulator) and any future hardware-backed engine
must inherit from CVEngineBase.  The base provides safe no-op defaults for
methods that only the simulator needs to implement (e.g. set_engaged), so the
controller can call them unconditionally without risk on real hardware.
"""

import numpy as np


class CVEngineBase:
    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def read_frame(self) -> "np.ndarray | None":
        raise NotImplementedError

    def get_metadata(self) -> dict:
        raise NotImplementedError

    def set_dwell_progress(self, frac: float) -> None:
        """Update the on-target dwell progress (0.0–1.0) for the kill-confirm arc."""

    def set_engaged(self, engaged: bool) -> None:
        """Signal that a RAT is actively being engaged.

        The simulator overrides this to move the crosshair onto target so that
        dwell-based hit confirmation can accumulate.  On real hardware the CV
        engine derives on_target from actual gimbal sensor data, so this is a
        deliberate no-op — calling it has no effect and cannot fabricate events.
        """

    def get_raw_frame(self) -> "np.ndarray | None":
        """Return the most recent raw (pre-annotation) frame, or None.

        Used by HitConfirmEngine to analyse the drone body without HUD
        artefacts (crosshairs, lock rings, etc.) causing false positives.
        Subclasses that separate raw from annotated frames should override this.
        """
        return None
