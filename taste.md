# Taste Profile: Doug Wagner

## Channels

### soft-warms
- Intent: Artistic warm color grade via NX-D Soft Warms presets, then Photoshop composite or print output. Film-era aesthetic (Tuscany 1968, France 1968, Boutique Reds). Final outputs are TIF for print, sRGB JPG for web, Nikon RGB JPG for archival.
- Signals: Rich tonal range that responds well to shadow lifting (LCH gamma 0.9). Strong foreground-to-background depth. Warm natural light or golden hour. Scenes with earthy tones (browns, golds, reds, woods) that benefit from pushed saturation and shifted hue. Landscapes, nature trails, wooded paths, animals in natural settings.
- NXD preset family: NXD Soft Warms (Browns Golds Oranges, Pinks Reds Purples, Blue Contrast, Woods, Exposure)
- NXD signature: Contrast -100, Saturation +100, Hue -100, LCH Gamma 0.9, complex chroma curves (3-5 control points), RGB Gamma 0.94, exposure varies by sub-preset
- Output: Full-resolution TIF from NX-D, then Photoshop PSB composite workflow. Final: sRGB JPG + Nikon RGB JPG + TIF
- Confidence threshold: 0.7

### soft-greens
- Intent: Natural green-toned treatment via NX-D Soft Greens presets. Garden and shade photography. Cooler and more natural than Soft Warms but still stylized.
- Signals: Lush vegetation, garden scenes, shaded natural areas, green foliage as dominant element. Benefits from warmer white balance shift (6253K). Scenes where green channel richness carries the image.
- NXD preset family: NXD Soft Greens (Garden Shade, Garden Shade Blue, Pink Late Afternoon, Jimi Hendrix Soft Greens)
- NXD signature: Contrast -100, Saturation +100, Hue -100, Color Temp ~6253K, LCH Gamma 1.0, minimal chroma curves (1 point)
- Output: Full-resolution TIF, sRGB JPG
- Confidence threshold: 0.65

### composite-base
- Intent: Base layer for multi-layer Photoshop composite (PSB/PSD). The Pandora Forest workflow: NEF → NX-D grade → TIF → Photoshop layered composite with background replacement, blending, and artistic retouching.
- Signals: Good subject-to-background separation. Clean edges around subjects. Interesting texture or detail in subject. Backgrounds that are either (a) worth keeping as-is for environmental composites, or (b) clean enough to replace. Multiple subjects in frame that create narrative possibilities.
- Output: Full resolution TIF, preserve all detail, no color correction. Routed to Photoshop/[project]/ directory structure.
- Confidence threshold: 0.7

### elimstat-product
- Intent: Product photography for Elimstat.com e-commerce. Clean, neutral, accurate color. Minimal post-processing. NX-D preset corrects for lighting conditions only — no artistic treatment.
- Signals: Product isolation on clean background. Even, diffused lighting. Sharp detail visibility across product surface. Neutral color rendition. Macro or close-up product detail. Indoor studio or controlled lighting setup.
- NXD preset family: NXD Elimstat (Rubber Mats for neutral daylight, Indoor Lighting for tungsten correction)
- NXD signature: Rubber Mats = all zeros (neutral), 6500K daylight WB. Indoor Lighting = Contrast -100, Sat +100, Hue -100 compensating for warm tungsten, Color Temp ~3848K.
- Output: sRGB, multiple sizes (2400px, 1200px, 600px), web-optimized JPEG quality 85
- Confidence threshold: 0.65

### bw-monochrome
- Intent: Black and white treatment via D800 Picture Control presets (MONOCHROME-1960s for vintage grain/tone, MONOCHROME-Severe for high contrast). Dramatic, graphic images.
- Signals: Strong shapes, geometric composition, dramatic light-to-shadow contrast. Scenes where color is secondary to form, texture, or mood. Silhouettes, high contrast natural light, architectural elements, strong leading lines.
- NXD preset family: D800 Settings/BW (MONOCHROME-1960s.NCP, MONOCHROME-Severe.NCP)
- Output: Grayscale TIF for print, grayscale JPEG for web
- Confidence threshold: 0.7

### instagram
- Intent: Social media post, square or 4:5 crop. Quick-turnaround share from any shoot.
- Signals: Strong single subject with visual impact at small size. Good negative space for text overlay. Compositions that survive aggressive cropping. Eye-catching color or mood. The kind of image that stops a scroll.
- Output: Center crop to 1:1 or 4:5, sRGB, 1080px wide, sharpen for screen
- Confidence threshold: 0.6

## Global Preferences
- Favor compositions with strong foreground-to-background depth
- Prefer images where the subject fills 40-60% of the frame
- Weight macro detail shots higher for elimstat-product channel
- Penalize obvious motion blur unless artistic intent is clear
- Images can route to multiple channels (a woodland scene might be both soft-warms and composite-base)
- When scoring for soft-warms vs soft-greens, key differentiator is dominant color palette: warm earth tones → soft-warms, dominant greens/cool vegetation → soft-greens

## NXD Preset Reference
The NXD presets in this project encode specific Nikon Capture NX-D adjustments as XMP metadata. Key parameters that define each preset's creative intent:
- **Tone curves** (TC_RGB, TC_R, TC_G, TC_B): per-channel response curves
- **LCH curves** (ML=lightness, CL=chroma-lightness, CR=chroma, HU=hue rotation): color-specific adjustments
- **Picture Control**: contrast, saturation, hue, sharpening, brightness
- **White Balance**: color temperature and method (recorded vs. manual)
- **Exposure compensation**: EV offset from metered exposure

## Confidence Calibration
- 0.9-1.0: "I would definitely process this for this channel"
- 0.7-0.9: "Strong candidate, worth reviewing"
- 0.5-0.7: "Maybe, depends on the rest of the shoot"
- Below 0.5: "Probably not, unless nothing better exists"
