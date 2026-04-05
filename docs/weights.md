Here's the side-by-side analysis:

### Confidence Scores

| Channel | Threshold | Claude | OpenAI | Delta | Routing Differs? |
|---|---|---|---|---|---|
| **soft-warms** | 0.70 | 0.85 | 0.85 | 0.00 | No -- both route |
| **soft-greens** | 0.65 | 0.75 | 0.80 | +0.05 | No -- both route |
| **composite-base** | 0.70 | 0.70 | 0.75 | +0.05 | No -- both route |
| **elimstat-product** | 0.65 | **0.15** | **0.30** | +0.15 | No -- both reject |
| **bw-monochrome** | 0.70 | **0.45** | **0.50** | +0.05 | No -- both reject |
| **instagram** | 0.60 | **0.65** | **0.90** | **+0.25** | No -- both route, but... |

### Key Observations

**They agree on what to route.** Both models send this photo to the same 4 channels (soft-warms, soft-greens, composite-base, instagram) and reject the same 2 (elimstat-product, bw-monochrome). For this image, the routing outcome is identical.

**OpenAI scores consistently higher.** GPT-4o gave higher or equal scores on every single channel. It's more "generous" -- a known pattern where GPT-4o tends toward agreeable/optimistic scoring.

**The instagram gap is the big one (+0.25).** Claude gave 0.65 (barely over threshold) with a specific critique: "composition is horizontal and may not survive square cropping well. Dogs are somewhat small in frame for social media impact." OpenAI gave 0.90 with vague praise: "Strong subject, clear negative space, and eye-catching composition." Claude's reasoning shows it actually considered your taste.md's crop requirement (1:1 or 4:5) and judged the composition against it. OpenAI didn't.

**Claude is more specific and critical.** Claude identified "two distinct dogs on leashes," noted the horizontal composition problem for Instagram, and gave a definitive "Not product photography" for elimstat-product (0.15 vs 0.30). OpenAI hedged more.

**elimstat-product shows calibration quality.** Both correctly rejected it, but Claude's 0.15 shows sharper discrimination -- it recognized this isn't even close. OpenAI's 0.30 leaves more ambiguity.

### Bottom Line

For **your** use case -- where the whole point is a taste-driven router that respects your creative intent -- **Claude is the better scorer**. It reads the taste.md signals more carefully, gives more actionable reasoning, and its lower scores on weak matches give you more headroom between "definitely route" and "definitely skip." OpenAI's generosity means edge-case images are more likely to sneak into channels where they don't belong.

The danger of OpenAI's optimism becomes real at scale: with hundreds of images, that +0.25 instagram inflation will route photos that Claude would correctly flag as borderline.