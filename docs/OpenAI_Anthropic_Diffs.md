Here are the key differences between the two backends:

**Models**
- **Claude**: `claude-sonnet-4-20250514` (Sonnet 4)
- **OpenAI**: `gpt-4o`

**Run**
bridge-assist score --taste ./taste.md --backend claude
bridge-assist score --taste ./taste.md --backend openai

**Image detail level**
- **Claude**: Sends the full resized image (up to 2048px) at whatever quality fits under 4.5MB. No detail flag -- Claude processes the full resolution it receives.
- **OpenAI**: Uses `"detail": "low"` (line 233), which means GPT-4o processes the image as a fixed 512x512 thumbnail. This is a **cost optimization** but means OpenAI is literally seeing less detail than Claude. For a D800's 36MP files where you care about sharpness, bokeh quality, and subtle tonal transitions, this is a significant handicap.

**Response format**
- **Claude**: Asked to return raw JSON. The parser uses regex fallback if the model wraps it in markdown or other text.
- **OpenAI**: Uses `response_format: {"type": "json_object"}` (structured output mode) and asks the model to wrap scores in a `{"scores": [...]}` envelope. More reliable JSON parsing, but the extra prompt append (line 238) slightly changes what the model sees.

**Practical implications for your taste-based scoring**
- Claude is seeing a ~2048px image at quality 85 -- enough to judge bokeh character, skin tones, tonal rolloff, and the subtle signals your `taste.md` channels care about (e.g., "warm tonal rolloff" for soft-warms, "fine detail" for elimstat-product).
- OpenAI at `detail: "low"` is working from a 512px thumbnail. It can judge broad composition and color palette but will struggle with texture/sharpness distinctions that separate your channels.

**Cost**
- Claude Sonnet 4 vision: ~$3/M input tokens for images
- GPT-4o at `detail: "low"`: significantly cheaper per image (~$0.15 per low-detail image)

**Bottom line**: As currently configured, Claude will give you meaningfully better scoring for your use case because it's seeing 4x the resolution. If you wanted a fairer comparison, you'd change OpenAI's `detail` from `"low"` to `"high"` -- but that increases cost substantially. Running both and comparing the JSON scores would tell you whether the quality gap matters in practice for your specific channels.

If you want to switch to Agent mode, I can bump OpenAI to `"detail": "high"` and run both backends so you can compare their scores side by side on the same image.

Done. OpenAI will now process the full-resolution image (up to 2048px) instead of a 512px thumbnail. To compare both backends on the same image, run:

```bash
bridge-assist score --taste ./taste.md --backend claude
bridge-assist score --taste ./taste.md --backend openai
```

Note that the second run will overwrite `scores.json` with OpenAI's results. If you want to preserve both for comparison, save a copy after each:

```bash
bridge-assist score --taste ./taste.md --backend claude
cp .bridge-assist/scores.json .bridge-assist/scores-claude.json

bridge-assist score --taste ./taste.md --backend openai
cp .bridge-assist/scores.json .bridge-assist/scores-openai.json
```

Then you can diff the two files to see how their confidence scores and reasoning compare channel by channel.