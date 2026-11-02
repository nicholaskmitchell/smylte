package com.nicholaskmitchell.smylte

/// The page's background colour, which the window paints behind the status and
/// navigation bars so the app reads as one surface.
///
/// The page already says what it is: `syncThemeColor` (appearance.ts) keeps
/// `<meta name="theme-color">` on the live --bg for exactly this purpose in
/// mobile browsers. So the host reads that standard tag rather than speaking
/// the desktop bridge, which it cannot answer anyway: a WebView interception
/// sees no request bodies, and every bridge verb is a POST with one.
object ThemeColour {
    /// `#rgb` or `#rrggbb` as an opaque ARGB int, or null.
    fun parse(text: String?): Int? {
        val t = text?.trim() ?: return null
        if (!t.startsWith("#")) return null
        val hex = t.substring(1)
        if (!hex.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }) return null
        val rgb = when (hex.length) {
            3 -> hex.map { "$it$it" }.joinToString("").toInt(16)
            6 -> hex.toInt(16)
            else -> return null
        }
        return (0xFF shl 24) or rgb
    }

    /// Should the bar icons be dark? Whichever of black and white contrasts
    /// more with `colour`, by WCAG relative luminance. Black wins above 0.179.
    fun wantsDarkIcons(colour: Int): Boolean {
        fun channel(shift: Int): Double {
            val c = ((colour shr shift) and 0xFF) / 255.0
            return if (c <= 0.03928) c / 12.92 else Math.pow((c + 0.055) / 1.055, 2.4)
        }
        val luminance = 0.2126 * channel(16) + 0.7152 * channel(8) + 0.0722 * channel(0)
        return luminance > 0.179
    }

    /// Injected after each page load. Watches the theme-color tag and reports
    /// it, as hex, whenever it changes.
    ///
    /// A custom theme's --bg can be any CSS colour (the Appearance editor takes
    /// OKLCH on purpose), so anything that is not already hex is painted on a
    /// 1x1 canvas and read back, as desktop.ts `toHex` does, including its
    /// check that the engine parsed the value at all: an unparseable value
    /// would otherwise read back as the white backdrop.
    ///
    /// evaluateJavascript is not subject to the page's CSP, and this script
    /// fetches nothing.
    const val WATCH_SCRIPT = """
(function () {
  if (window.__smylteThemeWatch) return;
  window.__smylteThemeWatch = true;
  var last = '';
  function hex(v) {
    if (/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v)) return v;
    try {
      var c = document.createElement('canvas');
      c.width = 1; c.height = 1;
      var x = c.getContext('2d', { willReadFrequently: true });
      if (!x) return '';
      x.fillStyle = '#000000'; x.fillStyle = v; var a = x.fillStyle;
      x.fillStyle = '#ffffff'; x.fillStyle = v;
      if (x.fillStyle !== a) return '';
      x.fillStyle = '#ffffff'; x.fillRect(0, 0, 1, 1);
      x.fillStyle = v; x.fillRect(0, 0, 1, 1);
      var d = x.getImageData(0, 0, 1, 1).data;
      return '#' + [d[0], d[1], d[2]].map(function (n) {
        return (n < 16 ? '0' : '') + n.toString(16);
      }).join('');
    } catch (e) { return ''; }
  }
  function send() {
    var m = document.querySelector('meta[name="theme-color"]');
    var v = m ? (m.getAttribute('content') || '').trim() : '';
    var h = v ? hex(v) : '';
    if (h && h !== last && window.SmylteAndroid) {
      last = h;
      window.SmylteAndroid.themeColour(h);
    }
  }
  new MutationObserver(send).observe(document.head, {
    subtree: true, childList: true, attributes: true, attributeFilter: ['content']
  });
  send();
})();
"""
}
