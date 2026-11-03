// The contrast helpers moved to ../contrast.ts when the Android client's
// wallpaper accent began measuring at runtime. Re-exported here so the token
// tests keep their import.
export { composite, contrast, luminance, parseColor } from '../contrast'
