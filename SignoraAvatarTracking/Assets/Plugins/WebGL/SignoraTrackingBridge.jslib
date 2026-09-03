mergeInto(LibraryManager.library, {
  Signora_SetUnityReady: function () {
    if (typeof window.SignoraUnityReady === "function") window.SignoraUnityReady();
  },

  Signora_ReportCalibration: function (statePointer) {
    var state = UTF8ToString(statePointer);
    if (typeof window.SignoraCalibrationState === "function") window.SignoraCalibrationState(state);
  }
});

