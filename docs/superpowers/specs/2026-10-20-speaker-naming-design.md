# Automatic speaker naming from a local voice gallery (design)

> **Status:** locked design v1.1 (2026-10-20), approved by user after builder check.
>
> **Brainstorm session:** 2026-10-20. Builds on the speaker spike (commits
> d007c32, b9969e4, 99da7b2; DEV_LOG entry 2026-10-20). Spike scripts
> `scripts/spike_speaker_writeback.py` and `scripts/spike_speaker_id.py` are the
> reference implementation for every Plaud call and for embedding extraction.

## 1. Intent

Plaud names only the account owner's voice automatically; every other speaker
stays `Speaker N` until the user names them by hand, per recording. The
summaries, and the local `.md` files PlaudSync writes, carry those
`Speaker N` labels downstream: into the Claudie assistant and into meeting
notes in project folders.

PlaudSync should name speakers it recognises, learn from the names the user
gives in Plaud, and carry every later correction through to Plaud's summary
and to the local `.md`. The user keeps working in Plaud as today. They fill in
the names PlaudSync left out, or fix the ones it got wrong. Once in a while
they check the gallery in the PlaudSync UI.

**Plaud is the source of truth for names.** The gallery always follows what is
in Plaud now. PlaudSync's own writes are just a head start.

## 2. Goals

1. **Auto-name new recordings.** When a recording is ready (transcript and
   summary done), embed each Plaud speaker cluster. Match only the clusters
   still labelled `Speaker N` against the gallery. Every cluster scoring
   **≥ 0.75** against a person gets that person's name in Plaud:
   - in all three transcript surfaces (`trans_result`, content `transaction`,
     content `transaction_polish`),
   - in the original summary, in place.

   Unrecognised clusters stay `Speaker N`. The `.md` is then rewritten so it
   carries the names.
   - **Scope (user decision, changed 2026-10-21):** every recording still in
     Plaud whose transcript is ready, whether downloaded, `skipped`,
     `skipped_unknown_project` or failed, private recordings included. Only
     trashed recordings are out. The user reads the names in Plaud within about
     an hour of a meeting to recall who was there, *before* deciding the
     project, so naming cannot wait for classification. This replaces the
     original "only recordings with an `.md`" scope.
   - **Without an `.md`:** names are written to Plaud only. The `.md` step is
     skipped (no retry), because the `.md` composed later from Plaud content
     already carries the names. Once an `.md` exists, renames rewrite it as
     usual.
   - **No wasted calls:** in a sync run a recording is learned only when the
     listing marks it transcribed (`is_trans`). A recording without a
     transcript costs no Plaud call; it becomes a candidate once Plaud has
     transcribed it, while it is inside the window.
   - **Partial `.md`:** the existing early write (transcript before summary,
     Hotfix H) stays. It may briefly show `Speaker N` until naming runs after
     the readiness gate. *(My call: do not touch the existing partial-write
     path.)*
2. **Learn from Plaud.** In the same scope, every cluster with a real name
   (not `Speaker N`) becomes a gallery sample for that person.
3. **Follow corrections.** When the user renames a cluster in Plaud, whether
   PlaudSync named it or the user did:
   - the sample moves to the new person;
   - the old name is replaced in the Plaud summary where it is still present;
   - the local `.md` is rewritten.

   The same applies when the user fills in a `Speaker N` cluster.
4. **Review gallery samples in the UI.** A new "Řečníci" section of the existing
   web UI lists flagged samples (§5.4) with an audio clip. The user listens,
   then confirms the name or assigns another. Assigning another name renames
   the cluster in Plaud, which then cascades as in goal 3. A toggle shows
   **all** samples, for checking.
5. **Bounded re-check plus one-off backfill.** Corrections are picked up for
   recordings inside the re-check window (default 14 days, the user's habit).
   A CLI parameter processes an older period once.
6. **Off switch.** A config flag disables the whole feature. Sync then behaves
   exactly as today.

## 3. Non-goals

- No confirmation step before writing names to Plaud. The user explicitly
  chose direct writes and fixing in Plaud. This replaces the spike's
  "suggest + confirm" decision.
- No name-alias table. A person known under two names is fixed by renaming in
  Plaud or in the review UI, as with spike case 2.
- No embeddings or voice data leave the machine. Plaud's own `embeddings` field
  is not used: it is empty.
- No OS notifications.
- No re-transcription (`/ai/transsumm`) and no new summary tabs
  (`/ai/sum_new_note`). Both are dead ends from the spike.
- No editing of downstream copies outside PlaudSync's own `.md` files. Claudie
  pulls data on its own.
- No changes to the classification or routing rules for where `.md` files go.

## 4. Anti-goals (failure even if it "works")

- **Wrong names spreading.** A wrong name in a summary reaches Claudie and
  project meeting notes and must be fixed by hand. Precision beats coverage:
  the threshold stays at 0.75, a closed decision. Never lower it to gain
  coverage.
- **Overwriting the user's work.** PlaudSync never renames a cluster the user
  named. It writes only to `Speaker N` clusters, plus renames the user
  triggers explicitly from the review UI.
- **Getting the account banned.** The user is wary of Plaud API volume. Every
  per-run re-check must be cheap, and backfill must be throttled.
- **Breaking sync.** A failure anywhere in speaker naming must not fail or
  delay the normal download and `.md` write.
  - Log the failure and send it to Sentry.
  - Write the `.md` as today.
  - Retry speaker naming on a later run inside the window.
- **Leaking names.** Person names are business identifiers. They never appear
  in log or exception messages: use `logger.bind` / `set_tag` (CLAUDE.md
  privacy rules).

## 5. How it works

### 5.1 Unit of work: the Plaud cluster

A *cluster* is `(plaud_id, original_speaker)`. Its current label is the
`speaker` value of its segments in `trans_result`. A label matching
`^Speaker \d+$` counts as unnamed.

A cluster's embedding comes from these decided parameters, which are
spike-validated and closed:

- **Model:** sherpa-onnx with CAM++
  (`3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx`).
- **Segments:** longest first, each ≥ 1.5 s, capped at 120 s total per cluster.
- **Audio read:** from the local audio via `SoundFile.seek`, never decoding the
  whole file. Local "`.mp3`" files are OGG Opus at 16 kHz and libsndfile reads
  them directly.
- **Segments past the end of the audio:** skip them. 8/62 spike recordings had
  a transcript 25–30 s longer than the audio, cause unknown.

Plaud sometimes splits one person into two clusters. The same name on several
clusters of one recording is normal and allowed.

### 5.2 Gallery

These parts are stored in the existing SQLite state DB. Embeddings never go to
the cloud.

- **Sample:** one per named cluster. Holds plaud_id, original_speaker, person
  name, embedding, origin, review status and consistency score.
  - Origin is one of: `user` (named in Plaud by the user), `auto` (named by
    PlaudSync), `review` (named in the review UI).
- **Person centroid:** the mean of that person's *eligible* samples. Matching
  uses cosine similarity against centroids.
- **Eligible:** not flagged and not excluded.
  - An `auto` sample becomes eligible only after its recording leaves the
    re-check window without the user changing it. *(My call: this stops
    PlaudSync training on its own unverified guesses.)*
- **Unnamed clusters (user decision):** embeddings of `Speaker N` clusters
  are kept so a re-check does not re-read or re-download audio. They are kept
  only while the recording is inside the re-check window. They are deleted
  when it leaves the window unnamed. If the feature is turned off, all stored
  embeddings are kept until the user deletes them.
  *(My call: turning the feature off is a pause, not a purge.)*
- **Per-recording snapshot:** for each processed recording, the last-seen
  `original_speaker → label` map and which labels PlaudSync wrote. This is how
  a user change is told apart from PlaudSync's own write.

### 5.3 Per-run flow (inside the sync run, after content is complete)

1. **New recordings** (transcript just became ready, §2 goal 1 scope):
   1. Fetch `trans_result`.
   2. Embed all clusters and store samples for the named ones.
   3. Match the `Speaker N` clusters.
   4. Write the names (§5.6).
   5. Then write the `.md`, if the recording has one.

   If the local audio is not there (`download_audio: false`), fetch it to a
   temporary location for embedding and delete it afterwards. *(My call.)*
2. **Re-check** of recordings inside the window, plus any recordings queued
   from the review UI (§5.5) regardless of age:
   1. Detect a changed cluster label (see §6.1 on cost). When the user renames
      a speaker, the Plaud app updates all three transcript surfaces; this was
      verified in the spike. So the rewritten `.md`, built from content
      `transaction`, picks the rename up without PlaudSync copying it across.
   2. Update the sample's person.
   3. Fix the summary (§5.6).
   4. Rewrite the `.md` at its current location from freshly fetched content.
   5. Re-match any remaining `Speaker N` clusters, because the gallery may have
      grown.
3. **Flagging:** recompute consistency (§5.4) for every person whose sample set
   changed.

### 5.4 Flagging samples for review

A sample's consistency is its cosine similarity to the centroid of the
person's *other* eligible samples. Below a flag threshold the sample is
flagged: excluded from the centroid until reviewed.
- A person with fewer than two samples cannot be scored and is not flagged.
- The flag threshold is the builder's to calibrate from the spike data in
  `%LOCALAPPDATA%\plaudsync\spike_speaker_cache\embeddings_campplus.npz`.
  Known points: true impostors reached 0.69 and genuine matches were mostly
  above 0.75.

A sample the user confirms in review is never re-flagged.

### 5.5 Review UI ("Řečníci" section)

The section sits in the existing FastAPI + Vite frontend, as a new menu
section.

- **Default list:** flagged samples, each showing:
  - person name,
  - recording title and date,
  - consistency score,
  - an audio clip of that cluster, cut from the local audio and served only to
    localhost.
- **Toggle:** shows all samples.
- **Actions per sample:**
  - **Confirm.** The sample becomes eligible and is never re-flagged.
  - **Assign another name.** Pick an existing person or type a new one. This
    renames the cluster in Plaud (§5.6) and cascades as in goal 3. The sample's
    origin becomes `review`.
    - **No Plaud writes from the UI.** The UI only records the action in a
      queue in the state DB. The next sync run drains the queue under
      `SyncLock`: rename in Plaud, then fix the summary, then rewrite the
      `.md` (if there is one). This works even if the recording is outside
      the window; only an entry whose recording is gone or trashed is dropped.
      *(My call: no Plaud writes from the UI process, so no race with a sync
      run.)*
    - The UI shows such a sample as "waiting for sync" until the queue entry
      is processed.
  - **Exclude** (noise or a bad recording). The sample is kept but never used.
    *(My call: covers the "vyřadit" case where no name fits.)*
- **Pending count:** the number of pending flagged samples is visible in the
  UI's menu.

If a recording's audio is not available locally, the item shows without a
clip.

### 5.6 Writing to Plaud

Use the spike-verified calls:

- **Cluster rename:** `PATCH /file/{id}` (`trans_result`) plus
  `POST /ai/update_source_info` twice (`transaction`, `transaction_polish`).
- **Summary in place:** `GET /ai/query_note` (header `file-id`), then
  `POST /ai/update_note_info` on the `auto_sum_note`.
  - **Writing PlaudSync's own names:** replace `Speaker N` with the regex
    `(?<!\w)Speaker N(?!\d)`. It covers `[...]`, `*...*` and `**...:**`
    wrappers.
  - **After a user rename:** replace the old name with the new one, but only
    if the old name no longer labels any cluster in that recording. This
    avoids rewriting a real, different person who shares the name.
  - **If Plaud already updated the summary itself:** do nothing. Plaud
    sometimes does, sometimes not.
- **Concurrency:** re-read just before writing. If the cluster labels changed
  since PlaudSync read them, for example because the user is editing in the
  app, skip and retry next run. Whether `file_version` gives a cheaper check is
  for the builder to verify.
- **Readiness gate** (closed): listing `is_trans && is_summary` and content
  `task_status == 1`. This matches the existing "content complete" check.

### 5.7 Backfill CLI

```
python -m plaudsync speakers backfill --since YYYY-MM-DD [--delay SECONDS]
```

It does the same work as §5.3 for every in-scope recording (§2 goal 1)
created on or after `--since`, ignoring the window. It has no listing, so a
recording without a transcript costs one `trans_result` fetch and stays
unprocessed.

- **Learning and naming:** it learns from named clusters, auto-names the
  `Speaker N` clusters, and propagates the results to the summary and `.md`.
- **Throttling:** it is throttled (a default delay between Plaud calls). It is
  resumable: it remembers which recordings are done, so an interrupted run
  continues.
- **Locking:** it takes the existing `SyncLock` so it never runs alongside a
  tray-triggered sync.
- **Old recordings:** `auto` samples from recordings already outside the
  window become eligible immediately, since the user will not revisit them.
  They do not count toward the kill criterion (§7). *(My call.)*
- **Gallery bootstrap:** this is also how the gallery is filled the first time.
  Reusing the spike's local cache to avoid re-downloading audio is allowed, but
  Plaud's current labels win.

### 5.8 Config and dependencies

- **Config:** `config.yaml` gains `speaker_naming: {enabled: true}`.
  - The re-check window reuses the existing `recheck_window_days`, so there is
    no second knob. *(My call.)*
  - The 0.75 threshold is a code constant, not config.
- **Model file:** lives under the state root. On first use it is downloaded
  from a pinned URL and verified by SHA-256. *(My call.)*
- **Dependencies:** add `sherpa-onnx`, `soundfile` and `numpy` to
  `pyproject.toml` (today they are only in the venv).
- **Frontmatter fix, in scope because `.md` files get rewritten:**
  `DetailMeta.speakers_count` is always 0, because Plaud's `embeddings` is
  empty. Count distinct speakers from the transcript instead.

## 6. Open points left to the builder

1. **Cheap change detection.** Before designing the re-check, find out whether
   the listing or detail carries a marker that changes when a speaker is
   renamed (`edit_time`, `version`, `file_version`).
   - **If a marker exists:** re-fetch `trans_result` only for changed
     recordings.
   - **If not:** re-check each in-window recording at most every 6 hours.
     *(My call. It bounds API volume to roughly 4 calls per recording per day.)*
2. DB schema, module layout, clip format and length, and UI layout.
3. Calibrating the flag threshold (§5.4).
4. Testing per CLAUDE.md: integration-first with VCR cassettes for every Plaud
   endpoint, including the write endpoints, recorded against a throwaway test
   recording. Pure matching and flagging logic is unit-tested with synthetic
   vectors. How to keep the ~30 MB ONNX model out of the default test run is
   the builder's call.
5. Writer/Reviewer pattern is mandatory: the work touches an external API
   contract and biometric data.

## 7. Success

- **New recordings get names.** A new recording with known voices has the
  recognised names in Plaud (transcript and summary) and in its `.md` on the
  first sync run after its content is complete.
- **Corrections reach the `.md`.** A rename the user makes in Plaud within the
  window reaches the Plaud summary and the local `.md` without any action
  beyond the rename.
- **Kill criterion.** Log every user correction of an `auto` name, as a count
  with no names in the message. Only names auto-assigned to recordings inside
  the window count, not those from backfill. If more than 5 % of these are
  corrected in the first month, stop auto-writing and revisit the "suggest +
  confirm" mode.
