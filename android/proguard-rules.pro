# The page calls these by name through addJavascriptInterface, so R8 must not
# rename or drop them. proguard-android-optimize.txt carries the same rule; it is
# restated here so the client does not depend on that file keeping it.
-keepclassmembers class com.nicholaskmitchell.smylte.PageBridge {
    @android.webkit.JavascriptInterface <methods>;
}
