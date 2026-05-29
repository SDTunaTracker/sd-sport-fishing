(function () {
  var params = new URLSearchParams(window.location.search);
  window.FEATURES = {
    OCLA_PUBLIC:  false,   // flip to true when OC/LA is ready to launch
    _previewOcla: params.get('preview_ocla') === 'true',
  };
  // SHOW_OCLA is the single gate checked by all UI code
  window.FEATURES.SHOW_OCLA = window.FEATURES.OCLA_PUBLIC || window.FEATURES._previewOcla;
})();
