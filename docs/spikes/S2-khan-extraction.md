# Spike S2 — Khan Academy extraction (run 1)
**Date:** 2026-06-09 · **Verdict: direct scrape NO-GO; legitimate route found via Kolibri — scope inverts to transcripts**

## Direct scrape: NO-GO
- khanacademy.org serves a Fastly **"Client Challenge"** (JS proof-of-work) to all non-browser clients — even `robots.txt` is walled.
- The internal GraphQL API rejects queries without per-deploy `hash=` parameters.
- Conclusion: Khan actively blocks automated access. A browser-automation scrape would mean circumventing an explicit technical countermeasure — fragile at ~30k-page scale and against the spirit (and likely letter) of their ToS, regardless of the content's CC license. **Do not build this.**

## The legitimate route: Kolibri channel database
[Learning Equality](https://learningequality.org) is Khan Academy's sanctioned offline-distribution partner. Their Studio API is public and structured:

- Channel list: `https://studio.learningequality.org/api/public/v1/channels`
- **Khan Academy (English - US curriculum)**: channel `c9d7f950ab6b5a1199e3d6c