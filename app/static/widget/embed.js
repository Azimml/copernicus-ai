(function () {
  if (window.__CB_WIDGET_LOADED__) return;
  window.__CB_WIDGET_LOADED__ = true;

  var currentScript = document.currentScript;
  var scriptSrc = currentScript && currentScript.src ? currentScript.src : "";
  var inferredBase = scriptSrc ? scriptSrc.replace(/\/widget\/embed\.js(?:\?.*)?$/, "") : "";
  var baseUrl = (window.CB_WIDGET_BASE_URL || inferredBase || "").replace(/\/$/, "");
  var version = window.CB_WIDGET_VERSION || "20260517-1";
  if (!baseUrl) return;
  if (!window.CB_WIDGET_BASE_URL) window.CB_WIDGET_BASE_URL = baseUrl;

  var css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = baseUrl + "/widget/widget.css?v=" + encodeURIComponent(version);

  var root = document.createElement("div");
  root.id = "cb-widget-root";

  var script = document.createElement("script");
  script.src = baseUrl + "/widget/widget.js?v=" + encodeURIComponent(version);
  script.async = true;

  document.head.appendChild(css);
  document.body.appendChild(root);
  document.body.appendChild(script);
})();
