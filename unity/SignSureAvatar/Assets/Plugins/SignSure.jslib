// Unity -> React events. React subscribes with addEventListener from react-unity-webgl.
mergeInto(LibraryManager.library, {
  SignSureEmit: function (evtPtr, payloadPtr) {
    var evt = UTF8ToString(evtPtr);
    var payload = UTF8ToString(payloadPtr);
    if (typeof window.dispatchReactUnityEvent === 'function') {
      window.dispatchReactUnityEvent(evt, payload);
    }
  },
});
