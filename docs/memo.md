# Memo: Marketing A/B Test Audit

**To:** Marketing / Growth stakeholders
**Re:** Did the ad campaign work, where does it pay off, and should we scale it?

All dollar figures below are illustrative and editable (assumed CPM of $10 per 1,000
impressions and $25 per conversion). The conversion numbers are real, computed from the
Kaggle "Marketing A/B Testing" dataset (588,101 users: 564,577 in the ad group, 23,524
in the PSA control group). Every number here comes from the analysis scripts.

## Bottom line

The campaign produced a real, statistically significant lift in conversion. The effect
is concentrated almost entirely among users who saw a very high number of ads, and there
is no measurable lift at low or medium exposure. At the illustrative cost assumptions the
campaign does not pay for itself (ROAS 0.775), so the decision hinges on the true cost of
impressions and the true value of a conversion.

## 1. Did the campaign change conversion?

Yes, and it is not noise. Using a two-proportion z-test on the randomized groups:

- Ad group conversion rate: 2.5547 percent (14,423 of 564,577).
- Control (PSA) conversion rate: 1.7854 percent (420 of 23,524).
- Absolute lift: +0.77 percentage points (95 percent CI 0.60 to 0.94 pp).
- Relative lift: +43.1 percent.
- p-value: 1.7e-13 (z = 7.37).

Because users were randomized into ad versus PSA, this overall lift is a genuine causal
estimate. The confidence interval excludes zero, so the effect is real.

## 2. Where does more exposure stop paying off?

We grouped users by how many ads they saw (1, 2 to 3, 4 to 7, 8 to 15, 16 to 31, 32 or
more) and compared ad versus control within each group, correcting for multiple
comparisons (Benjamini-Hochberg).

- The lift is concentrated in the highest-exposure band (32 or more ads): ad 9.30 percent
  versus control 5.78 percent, a +3.53 pp difference that is highly significant after
  correction (adjusted p 1.7e-16).
- Every band below that (1 through 16 to 31) is not statistically distinguishable from
  zero after correction. The small positive or negative differences there are sampling
  noise, not evidence that ads help or hurt.
- The top band holds about 66 percent of all ad impressions but accounts for essentially
  all of the incremental conversions.

Important caveat: the number of ads a user saw is not randomized. More engaged users both
see more ads and convert more, so these per-band results are observational and
descriptive, not causal. We cannot conclude that forcing more ads onto a user causes the
higher conversion seen in the top band. The only clean causal number is the overall lift
in section 1.

## 3. Economics at the illustrative assumptions

- Total ad impressions: 14,014,701. Total media cost: $140,147.
- Incremental conversions (from the causal lift): 4,343.
- Cost per incremental conversion: $32.27.
- Value of incremental conversions: $108,575. ROAS: 0.775.

At $10 CPM and $25 per conversion the campaign returns less than it costs (ROAS below 1).
This is a legitimate, assumption-dependent finding, not a data problem. It turns positive
if impressions can be bought below a break-even CPM of $7.75, or if a conversion is worth
more than the break-even value of $32.27.

## 4. Recommendation

Lead with the conservative figure. If we shift 25 percent of the impressions from the
least efficient reliable band (4 to 7 ads) into the highest band (32 or more), holding
total spend constant, the defensible estimated gain is about +56.5 incremental
conversions, roughly +$1,413 in value. An optimistic upper bound is +82.7 conversions
(about +$2,067), but that upper bound credits a "saving" from the 4 to 7 band whose
effect is not statistically significant, so we do not rely on it.

Both figures rest on a strong assumption: that the high-exposure band's efficiency would
hold if we bought more volume into it. It very likely would not, because high-exposure
users are self-selected engaged users, not users we can create by buying more
impressions. Treat the reallocation as an illustrative upper-bound sketch, not a promise.

Practical guidance:
- The campaign works, but its measurable payoff lives at very high exposure.
- Do not assume you can manufacture that payoff by buying more impressions.
- Profitability depends on CPM and conversion value. Negotiate CPM toward $7.75 or below,
  or confirm a conversion is worth at least $32.27, before scaling.

## 5. What we could and could not validate

- Randomization: the observed split (about 4 percent control) is consistent with an
  assumed 96/4 design (sample-ratio-mismatch test not rejected). The 0.04 intended split
  is an assumption that sits almost exactly on the observed share, so this check is
  assumption-dependent.
- Group balance: cannot be verified. The dataset has no pre-treatment characteristic to
  compare, so we cannot confirm the groups were alike before exposure.
- Time or novelty effects: cannot be tested. The dataset has no calendar dates, only day
  of week and hour of day of peak exposure, so there is no way to check for drift over the
  test period.
- The control group is small (23,524), and in the low-exposure bands it has very few
  conversions, which makes those band rates noisy.

In short: the headline lift is solid and causal; the band, timing, and economic
extrapolations are useful context but carry the caveats above.
