(function () {
  var params = new URLSearchParams(window.location.search);
  // SF Bay soft launch: ?preview_sfbay=true sticks for the browser tab
  // (sessionStorage) so deep links and reloads keep working while previewing.
  var previewSfbay = params.get('preview_sfbay') === 'true';
  try {
    if (params.get('preview_sfbay') === 'false') sessionStorage.removeItem('tt_preview_sfbay');
    else if (previewSfbay) sessionStorage.setItem('tt_preview_sfbay', '1');
    else previewSfbay = sessionStorage.getItem('tt_preview_sfbay') === '1';
  } catch (e) {}
  window.FEATURES = {
    OCLA_PUBLIC:  false,   // flip to true when OC/LA is ready to launch
    _previewOcla: params.get('preview_ocla') === 'true',
    SFBAY_PUBLIC: false,   // flip to true when the owner approves the SF Bay launch
    _previewSfbay: previewSfbay,
  };
  // SHOW_OCLA is the single gate checked by all UI code
  window.FEATURES.SHOW_OCLA = window.FEATURES.OCLA_PUBLIC || window.FEATURES._previewOcla;
  // SHOW_SFBAY gates the SF Bay region everywhere (regions.js, app.jsx, ui.jsx)
  window.FEATURES.SHOW_SFBAY = window.FEATURES.SFBAY_PUBLIC || window.FEATURES._previewSfbay;
})();
