# MacMedic Growth Plan

Improvement and go-to-market plan for MacMedic. This document is separate from
[`plan.md`](plan.md), which stays the architecture and engineering roadmap. This
one answers two questions. What do we change in the build so the app is worth
marketing. How do we get it in front of people who own end-of-life Intel Macs.

Written to be honest about the ceiling. The target hardware is being retired, so
the audience shrinks over time. The right motion is a genuinely good free tool
plus organic community reach, not paid acquisition. Success looks like becoming
the default recommended free maintenance tool in the Intel-Mac-keepalive
communities, not a revenue chart.

---

## 1. Positioning

One line. Keep your Intel Mac fast, cool, and useful past its expiration date.

Free, tiny, native, private. Lead with the four things competitors cannot all
claim at once.

- **Free and open source.** iStat Menus and CleanMyMac are paid. That is the
  wedge.
- **Tiny and native.** One 2-second timer, about 30 MB, no Electron, no daemons.
  This is a real virtue for old hardware and few rivals can say it.
- **Private.** No telemetry, no network calls. This pairs well with the app's
  own launch-agent blocklist that flags other vendors' telemetry.
- **Intel-first.** The SMC hardware depth (live CPU temp, fan RPM, power draw)
  is exactly the data that gets hard to reach on Apple Silicon. Own that framing.

Who it is for, in order of fit. People running OpenCore Legacy Patcher on
officially unsupported Macs. Owners of 2015 to 2020 Intel MacBooks, Mac minis,
and iMacs on the last supported macOS. Technical hobbyists who like small native
tools.

---

## 2. Build changes that make it marketable

Sequenced so each phase ends in something you can show. Do not start outreach
before Phase 0 is done. A red CI badge and an unsigned app that Gatekeeper
blocks will waste every first impression.

### Phase 0. Trust and foundation. Prerequisite to any marketing.

- **Make CI green.** CI is currently red. The cause is `requirements.txt`
  pinning `ruff>=0.5`, which floats to a newer ruff whose import-sort and format
  rules changed under the code. Pin `ruff` to an exact version, run `ruff check
  --fix` and `ruff format` once, and commit. Pin `mypy` and `pytest` too so a
  green run stays green.
- **Sign and notarize the app.** `plan.md` admits the build is ad-hoc. An
  unsigned app forces a right-click-Open dance and scares off non-technical
  users. Notarization is the single biggest install-funnel fix.
- **Publish the Homebrew cask.** The skeleton in `Casks/macmedic.rb` exists.
  Cut a real GitHub Release, fill the SHA, and make `brew install --cask
  macmedic` work. This is a passive discovery and trust channel for technical
  users.

### Phase 1. Make the headline features actually deliver.

- **Validate SMC coverage across Intel models.** The temp and power keys in
  `macmedic/smc.py` were verified on one 2019-2020 16-inch MacBook Pro. SMC keys
  vary across the Intel lineup, so the marquee feature may silently show nothing
  on other machines. Broaden the key lists, and when nothing reads, show an
  explicit "sensors unavailable on this model" state instead of a blank. The
  OpenCore community will report gaps per model, which feeds this directly.
- **Fix the split-interaction discoverability.** Left-click opens the card and
  right-click opens the full tool menu (`_status_clicked` in `macmedic/app.py`).
  Most users will never find the right-click menu. Add an affordance, for
  example a menu button in the card footer, or unify the surfaces.
- **Add per-item selection to Smart Clean, and prefer Trash.** `_run_clean`
  offers a single all-or-nothing Delete and deletes permanently. Give the user
  checkboxes and default to moving items to Trash. This removes the scariest
  moment in the app and makes it safe to recommend.

### Phase 2. Polish that converts a trial into a keeper.

- **Preferences pane.** Config today is hand-edited JSON at
  `~/Library/Application Support/MacMedic/config.json`. A simple settings window
  removes a real barrier for less technical users.
- **Light-mode support.** The card in `macmedic/panel.py` is tuned for dark
  only, per `plan.md`. Light-mode users may see poor contrast.
- **First-run onboarding.** A short walkthrough that explains Full Disk Access
  (needed for the cleaner) and what the app does. First launch is where you win
  or lose trust.

### Phase 3. Marketing assets. Build these once the product earns them.

- A README with an animated screen capture at the top, a clear feature list, and
  install options.
- A one-page landing site on GitHub Pages with screenshots and a download button.
- A 30 to 60 second demo video. Visual proof converts better than any prose.
- An [AlternativeTo](https://alternativeto.net) listing positioned as a free
  alternative to iStat Menus, CleanMyMac, and TG Pro.

---

## 3. Reaching Intel-Mac owners

Channels ranked by targeting quality, best first. The rule across all of them is
give before you take. Be a useful member of a community first. Post the tool
only where it genuinely answers a need. Mods ban drive-by promotion, and this
audience is allergic to it.

### Tier 1. The bullseye.

- **OpenCore Legacy Patcher community.** These people run unsupported Macs on
  purpose and are the most motivated audience alive for an EOL-focused tool.
  Reach them through the r/OpenCoreLegacyPatcher subreddit, the OCLP Discord, and
  GitHub discussions. Participate, answer thermal and battery questions, and
  mention the tool when it fits. This is the highest-conversion channel by a wide
  margin.
- **MacRumors forums.** The older-hardware and unsupported-Macs subforums have a
  steady flow of exactly this owner. A well-written thread with screenshots does
  well and keeps pulling search traffic for years.

### Tier 2. Broad but well-targeted.

- **Reddit.** r/mac, r/macOS, r/macbook, r/macmini, r/vintageapple, and
  r/lowendmac. Lead with a short screen recording. Tailor each post to the
  subreddit's norms rather than cross-posting the same text.
- **Hacker News, Show HN.** The angle plays well here. Native Python, tiny
  footprint, open source, and keeping old hardware out of landfill. Write a
  genuine post about why you built it. Timing matters, so aim for a weekday
  morning US time and be present to answer comments.
- **Lobsters**, if you have an invite. Similar crowd, high signal.

### Tier 3. Passive discovery and reach.

- **Homebrew cask.** Covered in Phase 0. Technical users find tools through brew.
- **GitHub discovery.** Set repository topics, get listed in awesome-macos style
  lists, and keep the README strong. Stars compound.
- **Product Hunt.** Lower fit for a niche utility, but a free launch that can
  send a spike. Worth one shot, not a priority.

### Tier 4. Content and search, the long game.

- **SEO blog posts** that answer ongoing search demand. Examples. How to check
  CPU temperature on an Intel Mac for free. How to speed up an old MacBook Pro.
  Is my Intel Mac obsolete. These capture people at the moment they feel the pain
  and keep working long after a forum post scrolls away.
- **Creator outreach.** YouTubers who make speed-up-your-old-Mac videos are a
  natural fit. Offer the tool, no strings. One video from the right creator can
  outperform every forum post combined.

### The news hook.

Apple's Intel sunset is a recurring press and community moment. When a new macOS
drops Intel support entirely, owners go looking for ways to keep their machines
useful. Have a post and an updated release ready to ride that wave.

---

## 4. Making outreach land

- **Frictionless install is the whole game.** Signed and notarized, plus
  Homebrew, plus a plain download. Every extra step loses people. This is why
  Phase 0 gates outreach.
- **Show, do not tell.** A 30 to 60 second capture beats paragraphs. Put it at
  the top of the README and in every post.
- **Have the kit ready before you post.** A one-liner, three or four
  screenshots, the demo clip, and a clear install section. Do not launch and then
  scramble.
- **Turn feedback into the roadmap.** Collect it through GitHub issues and
  discussions. The SMC coverage reports from the OCLP crowd feed Phase 1
  directly. That loop is your cheapest and best source of truth.

---

## 5. What to measure

Keep it privacy-respecting, consistent with the app's own stance. No invasive
in-app analytics.

- GitHub stars and their growth rate.
- GitHub Release download counts per version.
- Homebrew install analytics.
- Issue and discussion volume, and how much of it is SMC coverage per model.
- Referral sources to the landing page, if you host one.

Targets are modest by design. A realistic early win is being the top free
recommendation in one or two Intel-Mac communities and a steady trickle of
downloads that grows around each macOS Intel-sunset news moment.

---

## 6. Candor on strategy

Do not spend money on paid ads. The niche is shrinking and paid acquisition will
not pay back. The entire motion is a great free tool, organic community
presence, and search content that compounds. The realistic ceiling is a
respected, widely recommended free utility, not a business. Plan for that
outcome and it is very achievable. Plan for growth charts and it will disappoint.
