# EchoInsight V2 Report

- **Reviews processed:** 10
- **Initial catalog size:** 3
- **Avg relevant features per review:** 2.5
- **Positive assignments:** 19
- **Negative assignments:** 5
- **Neutral assignments:** 1
- **Avg classify time per review:** 13.46s
- **Avg classify time per feature:** 3.566s
- **Classify workers (local parallelism):** 3
- **Avg features per review:** 4.1
- **Validation pass rate:** 0.9
- **Elapsed:** 140.5s

## Validation Summary

- Validation enabled: true
- Validation mode: relevant-feature coverage only
- Pass rate: 0.9
- Failed reviews: 1
- Avg validation iterations: 1.3
- Avg validation seconds per review: 5.24s
- Common missing feature candidates: `battery_life` (1), `noise_cancellation` (1), `sound_quality` (1)

## Top Positive Features

- `general_satisfaction`: +8.00 total
- `ear_fit_stability`: +2.00 total
- `sound_quality`: +2.00 total
- `noise_cancellation`: +2.00 total
- `comfort`: +1.00 total
- `improvement_over_previous_version`: +1.00 total
- `battery_life`: +1.00 total
- `adjustability`: +0.50 total

## Top Negative Features

- `ear_fit_stability`: -1.50 total
- `general_satisfaction`: -1.00 total
- `condition`: -1.00 total
- `functionality`: -1.00 total

## Most Frequently Relevant Features

- `general_satisfaction`: relevant in 10 reviews
- `ear_fit_stability`: relevant in 4 reviews
- `sound_quality`: relevant in 2 reviews
- `noise_cancellation`: relevant in 2 reviews
- `adjustability`: relevant in 1 reviews
- `video_chat_performance`: relevant in 1 reviews
- `comfort`: relevant in 1 reviews
- `improvement_over_previous_version`: relevant in 1 reviews
- `battery_life`: relevant in 1 reviews
- `condition`: relevant in 1 reviews

## Initial Feature Catalog

### `ear_fit_stability`
> The ability of the product to stay securely in the ears during use.

Real quotes from sampled reviews:
- "Kept falling from my ears"

### `general_satisfaction`
> Overall positive sentiment about the product.

Real quotes from sampled reviews:
- "Bueno"
- "Muy lindo"

### `aesthetic_design`
> The visual appeal or look of the product.

Real quotes from sampled reviews:
- "Muy lindo"

## Per-Review Summary

### Review 0 (rating: 4.0)
- **Text:** These are so amazing I will proble buy another pair.
- **Relevant:** 1 (pos=1, neg=0, neu=0)
- **Validation:** pass=True iterations=1 confidence=0.95
- **Top scored:**
  - `general_satisfaction` score=+1.00 | These are so amazing

### Review 1 (rating: 5.0)
- **Text:** The sound quality is amazing. I love the noise cancellation, and I also like that I can adjust it if I need to. I video ...
- **Relevant:** 9 (pos=8, neg=0, neu=1)
- **Validation:** pass=False iterations=2 confidence=1.00
- **Missing feature feedback:** `sound_quality`, `noise_cancellation`, `battery_life`
- **Dynamic features added:** `adjustability`, `video_chat_performance`, `comfort`, `improvement_over_previous_version`, `sound_quality`, `noise_cancellation`, `battery_life`
- **Top scored:**
  - `ear_fit_stability` score=+1.00 | fit better in the ears
  - `general_satisfaction` score=+1.00 | The sound quality is amazing. I love the noise cancellation,
  - `comfort` score=+1.00 | These feel so much better and fit better in the ears than th

### Review 2 (rating: 5.0)
- **Text:** Good and works really well and stays in the ears well
- **Relevant:** 2 (pos=2, neg=0, neu=0)
- **Validation:** pass=True iterations=1 confidence=1.00
- **Top scored:**
  - `ear_fit_stability` score=+1.00 | stays in the ears well
  - `general_satisfaction` score=+1.00 | Good and works really well

### Review 3 (rating: 4.0)
- **Text:** I love the sound quality. The bass comes across very clear as if you’re in a room listening to a high-quality stereo. Th...
- **Relevant:** 4 (pos=3, neg=1, neu=0)
- **Validation:** pass=True iterations=2 confidence=0.95
- **Dynamic features added:** `sound_quality`, `noise_cancellation`
- **Top scored:**
  - `ear_fit_stability` score=-1.00 | the only issue I have with them is they fall out easily no m
  - `sound_quality` score=+1.00 | I love the sound quality. The bass comes across very clear a
  - `noise_cancellation` score=+1.00 | The noise cancellation is the best that I’ve experienced. Yo

### Review 4 (rating: 1.0)
- **Text:** These Airpods were clearly used. I didn't pay for refurbished Airpods and even if I had, they would have worked. These d...
- **Relevant:** 3 (pos=0, neg=3, neu=0)
- **Validation:** pass=True iterations=2 confidence=0.95
- **Dynamic features added:** `condition`, `functionality`
- **Top scored:**
  - `general_satisfaction` score=-1.00 | Really disappointed.
  - `condition` score=-1.00 | These Airpods were clearly used.
  - `functionality` score=-1.00 | These didn't work at all. Well, one did. But only one.

### Review 5 (rating: 5.0)
- **Text:** Great just hard to keep in my ear sometimes
- **Relevant:** 2 (pos=1, neg=1, neu=0)
- **Validation:** pass=True iterations=1 confidence=1.00
- **Top scored:**
  - `ear_fit_stability` score=-0.50 | hard to keep in my ear sometimes
  - `general_satisfaction` score=+0.50 | Great

### Review 6 (rating: 5.0)
- **Text:** My sister was staying with me for 6 hours. I got these to keep her entertained while I recovered. Worked very well!
- **Relevant:** 1 (pos=1, neg=0, neu=0)
- **Validation:** pass=True iterations=1 confidence=0.90
- **Top scored:**
  - `general_satisfaction` score=+1.00 | Worked very well!

### Review 7 (rating: 5.0)
- **Text:** Perfect earbuds for granddaughter and her work!
- **Relevant:** 1 (pos=1, neg=0, neu=0)
- **Validation:** pass=True iterations=1 confidence=0.95
- **Top scored:**
  - `general_satisfaction` score=+1.00 | Perfect earbuds

### Review 8 (rating: 5.0)
- **Text:** i was against these forever. My daughter got them and used them sparingly. My wife then used my daughters and raved abou...
- **Relevant:** 1 (pos=1, neg=0, neu=0)
- **Validation:** pass=True iterations=1 confidence=0.95
- **Top scored:**
  - `general_satisfaction` score=+1.00 | love them as well. Good sound quality and usefulness.

### Review 9 (rating: 5.0)
- **Text:** My granddaughter loves this
- **Relevant:** 1 (pos=1, neg=0, neu=0)
- **Validation:** pass=True iterations=1 confidence=1.00
- **Top scored:**
  - `general_satisfaction` score=+1.00 | loves this
