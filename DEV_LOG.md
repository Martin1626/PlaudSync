# PlaudSync — Dev Log

Ruční journal pro tracking kill criteria a non-obvious rozhodnutí. Přidávej odshora (nejnovější nahoru). Formát: `## YYYY-MM-DD — short title` + body.

---

## 2026-10-20 — spike: auto-pojmenování speakerů (write-back + přesnost lokální galerie hlasů)

**Cíl:** u nových schůzek doplnit jména speakerů z lokální galerie hlasů naplněné dřívějšími ručními přiřazeními v Plaudu; jména zapsat zpět do Plaud cloudu (přepis i shrnutí). Rozhodnutí z průzkumu (skill pruzkum): embeddingy lokálně přes **sherpa-onnx** (Apache-2, ONNX, bez PyTorch); Plaud `embeddings` mrtvé (pole v `/file/detail` je prázdné → `DetailMeta.speakers_count` je vždy 0, kandidát na bugfix). Revize BL-4 „embeddings NEVER“: hlasové otisky se smí ukládat lokálně, ne do cloudu.

**Write-back ([scripts/spike_speaker_writeback.py](scripts/spike_speaker_writeback.py), živě na testovací nahrávce):** jméno žije na 3 místech — `trans_result` (`PATCH /file/{id}`) + content `transaction` a `transaction_polish` (`POST /ai/update_source_info`); původní shrnutí in-place přes `POST /ai/update_note_info` (payload z web app JS, zrušený auto-matching). Re-read PASS + ověřeno ve web i mobilní appce. Slepé uličky: `/ai/transsumm` (nová transkripce = reset jmen), `/ai/sum_new_note` (funguje, ale nová záložka shrnutí).

**Přesnost ([scripts/spike_speaker_id.py](scripts/spike_speaker_id.py), read-only; cache přepisů/audia/modelů mimo repo v `%LOCALAPPDATA%\plaudsync\`):**
- *Test 2 — historie (60 dní, 175 nahrávek):* 83 % přepsaných má ≥1 ručně pojmenovaného speakera, 59 % řeči pojmenováno, 59 osob, 44 testovatelných (≥2 nahrávky s ≥30 s). Žádný Plaud cluster nenese 2 jména; 9× jedno jméno přes 2 clustery (Plaud rozdělil osobu). Medián segmentu 7,6 s.
- *Test 1 — leave-one-recording-out (54 nahrávek, 46 h, 211 pojmenovaných clusterů, 25 impostorů):* embedding na Plaud cluster (nejdelší segmenty ≥1,5 s, cap 120 s), galerie = centroid/osobu z ostatních nahrávek. **CAM++ (3D-Speaker) @ práh 0,70: precision 100 %, coverage 96,8 %, FAR 0/25, CPU 17 s/h audia → KC1–KC4 PASS.** Ostrý skok 0,65→0,70 (FAR 28 %→0) → produkčně **práh 0,75** (coverage 94,6 %). WeSpeaker ResNet34 (VoxCeleb) FAIL — skóre všech párů ≥0,8 (pravděpodobně feature mismatch), 44 s CPU/h.
- *Test 3 — audio:* lokální „.mp3“ jsou OGG Opus 16 kHz mono, libsndfile dekóduje přímo. U 8/62 nahrávek končí přepis o 25–30 s později než audio → přeskočeny; příčina **neznámá** (zkrácený soubor vs. časový posun).
- *Test 4 — připravenost (10 nejnovějších):* listing `is_trans`/`is_summary` se shoduje s content `task_status`; nepřepsané nahrávky mají prázdný `content_list`, mezistav nezachycen. Gate = listing flags + `task_status == 1`.
- *Test 5 — tvary ve shrnutích:* jen `Speaker N` (anglicky i v českých shrnutích), obalené `[...]`, `*...*`, `**...:**`; regex `(?<!\w)Speaker N(?!\d)` je pokrývá. JSON-wrapped notes ve vzorku nebyly.

**Lekce:** (1) Plný scan historie = ~1 400 API volání; spike skripty musí mít `--days` / `--limit` / `--delay` a cache od začátku (uživatel: šetřit Plaud API kvůli banu). (2) Celé dekódování 2h nahrávky = ~0,5–1 GB RAM → číst jen segmenty přes `SoundFile.seek`.

**Ruční kontrola:** `spike_speaker_id.py review` vygeneruje lokální HTML (audio ukázky, mimo repo, po kontrole smazat) se spornými případy — 1× jiná osoba (0,65), 12× cizí hlas podobný osobě z galerie (0,60–0,69; podezření na varianty jmen), 9× správně pod prahem 0,75. **Verdikty uživatele (poslechem):** 2 clustery mají v Plaudu **chybné jméno** (hlas patří jiné osobě) — jeden z nich model přiřadil se skóre 0,72; všech 12 „cizích podobných“ jsou opravdu různí lidé (žádné varianty jmen), tj. skutečný impostor dosahuje 0,69. Po opravě ground truth (184 genuine / 27 impostorů): **práh 0,70 → FAR 3,7 % = KC4 FAIL; práh 0,75 → precision 100 %, coverage 95,1 %, FAR 0 % = PASS.** Produkční práh 0,75 potvrzen. Poučení: ruční štítky v Plaudu nejsou 100% spolehlivé — galerie potřebuje možnost vyřadit chybný vzorek a produkce režim „návrh + potvrzení“ s poslechem.

**Otevřené:** GDPR čl. 9 (hlasy kolegů/klientů) → firma/DPO před produkcí (KC6); FAR jen na 25 impostorech (horní mez ~12 %) → ověřit v režimu „návrh + potvrzení“; souběh zápisů přes `file_version`; offset přepis vs. audio.

**Kill criteria:** KC1–KC4 PASS (CAM++), KC5 OK (0 smíšených clusterů), KC6 otevřené.

---

## 2026-06-01 — write_progress: tichá degradace na trvalém zámku (produkční crash)

**Symptom:** Log `c:\PlaudSync\.plaudsync\plaudsync.log` — jediný dnešní ERROR `SchedulerThread: pipeline raised uncaught exception` @07:59:32, traceback končí `PermissionError: [WinError 5] … .progress.*.tmp -> progress.json` ([progress.py](src/plaudsync/progress.py) `os.replace`, ř. 77). Jinak úspěšný běh (35 nahrávek zpracováno + skipnuto) se reportoval jako spadlá pipeline (`exit_code=1`). Scheduler crash NEpřežil fatálně — `except Exception` v [scheduler_loop.py](src/plaudsync/tray/scheduler_loop.py) ho zachytil, následující běh @12:00 prošel čistě.

**Root cause:** Navazuje na [[write_progress retry rezonance]] (29.5.) a [[clear_progress fix]]. Jittered backoff (30 pokusů, 1–4 ms → ~75 ms okno) byl laděný na **rychle pollujícího čtenáře** (WinError 32). 1.6. ale šlo o **delší zámek** (WinError 5 — typicky AV scan dotýkající se cíle), který 75ms okno přečkalo a smyčka po vyčerpání **raisla**. Dvě mezery: (1) okno krátké na multi-set-ms zámek, (2) `write_progress` na rozdíl od `clear_progress` na exhaustion stále raisoval, ač je `progress.json` jen UI nápověda.

**Fix (TDD):** [progress.py](src/plaudsync/progress.py) — (1) **eskalující** jitter strop (`min(0.004 + attempt*0.01, 0.1)`, 60 pokusů): těsné rané retry setřesou čtenáře, širší pozdější přečkají AV zámek (worst-case okno ~2 s vs. 75 ms); (2) na vyčerpání **degraduj tiše** (warn + úklid temp + return) místo raise — sjednoceno s `clear_progress`, další `write_progress` přepíše stale soubor. Test `test_write_progress_degrades_quietly_when_target_persistently_locked` (failing→green): monkeypatch `os.replace`→trvalý `PermissionError`, `sleep`→no-op; aserce že write neraisne, warne, a nenechá leaklý temp. Suite 473 passed, /review čistý ([]).

**Lekce:** Best-effort UI artefakt (progress.json) NESMÍ shodit sync pipeline. Retry smyčka proti zámku potřebuje okno škálované na **nejdelší realistický** zámek (AV scan ≫ pollující čtenář), ne jen na nejčastější. Degradace > raise u všeho, co běží uvnitř/kolem `run_sync` finally/handler (stejné poučení jako [[clear_progress fix]] a orphan sync_runs).

**Kill criteria:** žádné netriggernuto.

---

## 2026-05-31 — recheck window config + process-only-new main loop (feature)

**Cíl (uživatel):** s rostoucím Plaud cloudem nesmí čas zpracování růst kontrolováním starých, už neměnných záznamů; okno re-kontroly konfigurovatelné (default 14 dní). Symptom před opravou: `recordings_new=88` na každém běhu (přeskočené nahrávky re-zpracovávané donekonečna hlavní smyčkou).

**Brainstorm + spec + plán:** [spec](docs/superpowers/specs/2026-05-31-recheck-window-config-design.md), [plán](docs/superpowers/plans/2026-05-31-recheck-window-config.md). Zvolen přístup B (proces jen nové + delegace re-kontroly na bounded passy). Subagent-driven exekuce (10 tasků, per-task spec+quality review).

**Implementace:**
- `Config.recheck_window_days: int = 14` + `_validate_positive_int` (config.py), serializace + default YAML (config_io.py), frontend round-trip + Settings číselný input.
- `resolved_plaud_ids()` (state.py) — set downloaded/skipped (NE failed).
- Hlavní smyčka ([sync.py](src/plaudsync/sync.py)) zpracuje jen **nikdy neviděné** záznamy (jeden prefetch dotaz → O(1) test); `failed` se retryuje.
- Tři rolling passy řízené `config.recheck_window_days`.

**Klíčové non-obvious rozhodnutí (rework během exekuce):** Plán nejdřív rozšiřoval query retry passu + bespoke folder/catch-all logiku. Při Task 7 regresi vyšlo najevo, že to nereplikuje artifact-gate chování hlavní smyčky (5 recovery testů padlo: download_audio/sync_unclassified/classify_by_folder flip + project-added). Po konzultaci s uživatelem (recovery **omezená oknem**, plná parita) byl `_retry_skipped_unknown_project` **přepsán na delegaci na `_process_recording`** s `WaterfallClassifier` — jeden sdílený code path, plná recovery parita, **keyed na live listing meta** (řádek chybějící v listingu = trashnutý/smazaný → ponechán, trash-safe konzistentní s BL-8). 4 testy aktualizovány na novou sémantiku (recovery jen pro nahrávky přítomné v listingu).

**Lekce:** Recovery skipnutých nahrávek a hlavní download MUSÍ sdílet jeden code path (`_process_recording`). Dva paralelní implementace klasifikace/gate/download drift-ují (Fix A, Hotfix I/K, a teď tohle). Delegace > duplikace.

**Verifikace:** suite 472 passed, bandit 0 High/Medium, /security-review čistý (rework je security improvement — konsoliduje na hardened path). **Live běh: `recordings_new` 88 → 0** (run 1111); 35 skipů v okně re-kontrolováno, 53 starších už ne → výkonný cíl splněn.

**Kill criteria:** žádné netriggernuto. Follow-up (log only): rename `_retry_skipped_unknown_project` → `_retry_recent_skipped` (název už neodpovídá rozšířenému scope).

---

## 2026-05-29 — orphan sync_runs řádky u zdroje (crash před finish_sync_run)

**Follow-up na předchozí záznam** (read-side guard ve `_read_running`). Tady se opravuje **vznik** orphanů, ne jen jejich interpretace.

**Root cause:** [`run_sync`](src/plaudsync/sync.py) volá `finish_sync_run` pouze na success cestě (po download loopu). Výjimka před ním — typicky `list(client.list_recordings())` na ř. 735 (síťový drop: `ConnectionResetError`/`ProtocolError`/`SSLEOFError`), případně neobalené passy `_retry_skipped_unknown_project`/`_reclassify_recent` — propagne přes `finally` (jen `clear_progress`) ven, takže řádek zůstane `finished_at=NULL`. To je přesně orphan, který UI hlásí jako „running" napořád.

**Fix (TDD):** přidán `except Exception:` do `run_sync` — uzavře běh jako crashed (`exit_code=1`, counts 0) a re-raisne. Uzavření je best-effort (vlastní try/except + log), aby bookkeeping NIKDY nemaskoval původní výjimku — stejné poučení jako u [[clear_progress fix]] (finally/handler raise maskuje real error). Test `test_sync_closes_run_row_when_listing_crashes` (failing→green): crashing client → run_sync re-raisne ConnectionResetError, ale `sync_runs` řádek má `finished_at` set a `exit_code != 0`. Suite 461 passed.

**Defense-in-depth:** read-side guard (`_read_running`) + write-side close (`run_sync except`) se doplňují — orphany už nevznikají, a kdyby přesto (starší řádky, jiná cesta), reader je nepovažuje za živé.

**Kill criteria:** žádné netriggernuto.

---

## 2026-05-29 — zaseknutý „running" stav v UI (orphan sync_runs řádky)

**Symptom:** Po ručním spuštění nové verze trayu uživatel hlásil, že „synchronizace běží podezřele dlouho". `/api/state` ukazovalo `sync.status=running` se `started_at=2026-05-28T13:36` (~24 h), ale `progress=null`, `sync.lock` volný, poslední běh úspěšně doběhl (~3 s). Žádný sync reálně neběžel.

**Root cause:** [`_read_running`](src/plaudsync/ui/state_reader.py) bralo **jakýkoliv** `sync_runs` řádek s `finished_at IS NULL` jako „běžící". Běh, který spadne **před** `finish_sync_run` (síťová chyba uprostřed listingu/downloadu — viz orphan běhy 1028 @05:34 a 1061 @13:36 z 28.5., shodují se se scheduler crashy `ConnectionResetError`/`ProtocolError`), zůstane navždy nedokončený. Žádný liveness check → UI hlásí „running" donekonečna. NESOUVISÍ s clear_progress/jitter fixy (orphany jsou starší).

**Fix (TDD):** [state_reader.py](src/plaudsync/ui/state_reader.py) — nedokončený běh je „running" jen pokud `started_at > MAX(started_at dokončených běhů)`; pozdější dokončení dokazuje, že starší nedokončený je mrtvý. Parameterless SQL subquery, ISO-8601 řadí jako text. Testy: orphan→idle (failing→green) + guard genuine-running→running. Suite 460 passed.

**Reconcile živé DB:** 2 orphan řádky uzavřeny (`finished_at=started_at, exit_code=1`), scoped `started_at < MAX(finished started_at)` aby se neuzavřel živý běh. `/api/state` ihned `idle` (funguje i se starým readerem — žádný NULL-finished řádek nezbyl).

**Lekce:** „nedokončený řádek" ≠ „běžící proces". Liveness se musí ověřit (novější dokončený běh / lock / PID), ne odvozovat z absence finished_at. Crash před finalizací je první třída, na kterou myslet u stavových příznaků.

**Kill criteria:** žádné netriggernuto. Pozn.: opakované síťové crashe uprostřed syncu (28.5. 2×) by si zasloužily vlastní robustnost (graceful finish_sync_run i při výjimce v listing/download fázi) — kandidát na follow-up.

---

## 2026-05-29 — flaky atomicity test (write_progress retry rezonance)

**Symptom:** `test_concurrent_reader_never_sees_partial_payload` selhával ~30 % běhů (naměřeno 14/20). Ne aserce atomicity — `write_progress` raisoval `PermissionError [WinError 5/32]` z `os.replace`.

**Root cause (systematic-debugging + měření):** Instrumentace 200-write burstu ukázala těžký chvost v počtu retry pokusů; občas (2/201 zápisů) narazil na strop 20 → raise. Příčina dvojí: (1) **produkční** — fixní lineární backoff (1..19 ms) **rezonuje** s rovnoměrně pollujícím čtenářem, takže všech 20 pokusů padne do momentu, kdy čtenář drží handle (Windows blokuje rename otevřeného souboru — stejná lock-race třída jako [[clear_progress fix]]); (2) **test** — zero-sleep reader drží soubor otevřený ~100 % wall-clocku, což je patologie, kterou žádný atomic-rename nepřežije a v produkci nikdy nenastane (UI polluje `/api/state` v HTTP kadenci, ne v těsné smyčce).

**Měření strategií (30 burstů):** current (20, lineární) 5/30 failing; jitter (30, uniform 1–4 ms) 1/30. Jitter sám nestačí proti 100% duty čtenáři.

**Fix:** [progress.py](src/plaudsync/progress.py) — jittered backoff (`random.uniform(0.001, 0.004)`, 30 pokusů): dekoreluje retry od rytmu čtenáře (~5× méně exhaustions, reálný produkční hardening). [test_progress.py](tests/test_progress.py) — reader `sleep(0.5 ms)` per poll: zachová concurrency tlak (tisíce čtení přes burst, atomicity check plně v platnosti) bez nepřežitelné patologie. **Ověřeno: 30/30 běhů pass, suite 458 passed.**

**Lekce:** Retry-on-`os.replace`/`unlink` smyčky proti pollujícímu čtenáři MUSÍ jitterovat backoff (fixní schedule rezonuje). Stress testy nesmí modelovat kontenci, kterou cílová primitiva fyzicky nemůžou splnit.

**Kill criteria:** žádné netriggernuto.

---

## 2026-05-29 — clear_progress crash na Windows-locknutém progress.json

**Symptom:** Opakovaný log ERROR `SchedulerThread: pipeline raised uncaught exception` (14.5., 17.5., 21.5., 29.5.) s finální `PermissionError: [WinError 32] … progress.json … využivá jiný proces`. Úspěšný sync běh se reportoval jako spadlá pipeline.

**Layer (sync-debug):** Layer 4 (business/runtime logic) — env i síť čisté. Zbývající recent scheduler crashe (`SSLEOFError`, `ConnectionResetError`, `socket.gaierror`, urllib3 `ProtocolError`) jsou transientní síťové výpadky Plaud API, ne kódový bug.

**Root cause:** `clear_progress()` běží v `run_sync` `finally` bloku ([sync.py:832](src/plaudsync/sync.py#L832)). Volala `target.unlink()` a chytala jen `FileNotFoundError`. Na Windows `os.unlink` selže s `WinError 32`, když UI poller drží `progress.json` otevřený (`read_progress` mid-read). Raise ve `finally` přepsal `exit_code` a propagoval se jako uncaught exception do scheduleru — ačkoliv `finish_sync_run` už zapsal úspěch do DB. `write_progress` přitom stejný Windows race na `os.replace` už řešil retry smyčkou; `clear_progress` ten vzor postrádal.

**Fix:** [progress.py](src/plaudsync/progress.py) — `clear_progress` zrcadlí `write_progress`: retry s backoffem (20× ~1 ms) na `PermissionError`, po vyčerpání degraduje tiše (Loguru `warning` + ponechá stale soubor; další `write_progress` ho atomicky přepíše). Cleanup ve `finally` nikdy neraisuje. TDD: failing test `test_clear_progress_tolerates_locked_file` (drží otevřený handle) → green. Branch `fix/clear-progress-locked-file`.

**Kill criteria:** žádné netriggernuto.

**Pozn. (mimo rozsah):** Při běhu suite odhaleny 2 pre-existing problémy nezávislé na této opravě — (1) `test_concurrent_reader_never_sees_partial_payload` je flaky (`write_progress` `os.replace` občas vyčerpá 20 retry pod těžkým souběžným čtením); (2) 3 selhávající testy v `test_sync_retry_skipped_live_title.py` — viz následující záznam.

---

## 2026-05-29 — time-bomb v retry_skipped testech (absolutní datum vs. rolling okno)

**Symptom:** 3 testy v `test_sync_retry_skipped_live_title.py` selhávaly `downloaded == 0` (čekáno 1), `failed == 0` (žádný exception → nešlo o crash, řádek se prostě nestáhl).

**Root cause (systematic-debugging Phase 1–3):** NE produkční regrese. `_retry_skipped_unknown_project` selektuje jen řádky s `created_at_plaud >= now - days` (default 14). Testy psané 2026-04-30 seedovaly absolutní `created_at="2026-04-30…"`. Dnes (2026-05-29) je to 29 dní zpět → cutoff 2026-05-15 → `rows` prázdné → smyčka se nikdy nespustí. `classify()` i `lookup_project()` ověřeny izolovaně jako korektní; 454 ostatních testů procházelo → žádné jiné okno-bomby nehořely.

**Fix:** [test_sync_retry_skipped_live_title.py](tests/test_sync_retry_skipped_live_title.py) — seed přes helper `_recent_iso()` (`now - 1d`) místo absolutního data. Suite 457 passed.

**Audit ostatních windowed cest:** `_reclassify_recent` okno na `downloaded_at` (reclassify testy ho nastavují relativně → ok); `_retry_pending_content` na `created_at_plaud`, ale jeho testy už používají `datetime.now()` / `now - 15d` → ok. Time-bomba byla jen v tomto jednom souboru.

**Lekce:** Testy rolling-window dotazů MUSÍ seedovat datum relativně k `now`, nikdy absolutní literál. Projekt nemá freezegun — relativní datum je idiomatický fallback.

**Kill criteria:** žádné netriggernuto.

---

## 2026-05-03 — BL-8 shipped (Plaud-side trash detection)

User otázka „Co se stane v lokálním úložišti, když záznam přesunu do koše na Plaude?" odhalila, že BL-8 dosud žil pouze jako stub a trigger conditions ještě nebyly splněny (3 incidenty / 14d soak). User se rozhodl ship-nout preemptivně po skončení brainstormu.

**Brainstorm session:** 6 decisions locked v jedné session ([2026-05-03 spec](docs/superpowers/specs/2026-05-03-bl8-trash-detection-design.md)):
1. **Trash policy:** hard delete, žádný config flag (YAGNI na archive/mark — zamítnut 3× test surface).
2. **Untrash recovery:** fresh download via main loop; UPSERT whitelist rozšířen o `'trashed' → 'downloaded'`.
3. **Sentry alert:** hybrid — per-record trash silent (Loguru `info`), mass-detection guard captures s `error_kind='trash_mass_detection'`.
4. **UI:** šedá pill `smazáno` (BL-7 analog), žádný strike-through, žádný filter chip.
5. **UPSERT:** `'trashed'` přidán do whitelist.
6. **Batch safety guard:** combo (>10 AND >50% downloaded) — abort + Sentry; sync pokračuje. Hard-coded konstanty `_TRASH_BATCH_ABSOLUTE=10`, `_TRASH_BATCH_RATIO=0.5`.

**Architektura:** Approach X — nový `_detect_trashed` pre-pass v [sync.py](src/plaudsync/sync.py), runs first (mezi listing a `_retry_skipped_unknown_project`). Approach Y (rozšíření `_reclassify_recent`) zamítnut pro mísení concerns; Approach Z (per-record `/file/detail/{id}` check) zamítnut pro N+1 cost.

**Files touched:**
- [src/plaudsync/plaud_client.py](src/plaudsync/plaud_client.py) — `list_trashed()` metoda (mirror `list_recordings` s `is_trash=1`).
- [src/plaudsync/sync.py](src/plaudsync/sync.py) — `_detect_trashed` pre-pass + `_hard_delete_local` helper + wiring v `run_sync`. Aggregace `trashed_failed` do `failed_count`.
- [src/plaudsync/state.py](src/plaudsync/state.py) — `_SCHEMA` CHECK rozšířen o `'trashed'`, nová migrace `_migrate_status_add_trashed`, UPSERT whitelist rozšířen.
- [src/plaudsync/ui/state_reader.py](src/plaudsync/ui/state_reader.py) — Pydantic Literal type rozšířen.
- [frontend/src/api/types.ts](frontend/src/api/types.ts) — `RecordingStatus` union rozšířen.
- [frontend/src/pages/Dashboard/ProjectBadge.tsx](frontend/src/pages/Dashboard/ProjectBadge.tsx) — nová `'trashed'` větev s šedou pill před existující skipped větví.
- [tests/cassettes/test_sync/test_sync_happy_path_writes_file_and_updates_state.yaml](tests/cassettes/test_sync/test_sync_happy_path_writes_file_and_updates_state.yaml) — přidána `is_trash=1` empty-list interakce.

**Tests added (10 nových):**
- 7× trash detection (`tests/test_sync_trash_detection.py`): happy path, idempotent re-run, failed-row untouched, batch safety guard fires (20 downloaded / 11 trashed = 55 %), batch guard pass (12 downloaded / 7 trashed = 58 % ale 7 ≤ 10), untrash recovery, unrelated trash IDs no-op.
- 1× migration (`tests/test_state_migrations.py`): pre-BL-8 DB rebuilt to include `'trashed'` v CHECK, legacy rows preserved.
- 2× implicit ve změně cassette (existující `test_sync_happy_path_writes_file_and_updates_state` musel přijmout nový `is_trash=1` API call v sync flow).

**LoC odhad vs. realita:**
- Backend stub odhad: ~150 LoC. Realita: ~125 LoC v sync.py + ~25 v plaud_client + ~40 v state.py = ~190 LoC. Migrace větší než odhad (full table rebuild s 14 sloupci).
- Frontend stub odhad: 50 LoC. Realita: ~15 LoC (typ rozšíření 1 token + ProjectBadge větev 12 řádků). Stub overestimoval — žádná nová komponenta nepotřeba.
- Tests: 10 nových (vs. stub odhad ~10).

**Verification:**
- 444 pytest passing (přidáno 10 nových, 0 regrese).
- bandit clean — žádné nové issues z BL-8 (10 pre-existing low-severity findings v tray/ui subprocess + B101 asserts).
- `tsc --noEmit` clean.
- Frontend manual verification odložen na první real trash incident (no Vitest infra; BL-7 šel stejně).

**Stubs:** [BL-8 stub](docs/superpowers/specs/2026-04-30-bl8-trash-detection-stub.md) superseded by [BL-8 design](docs/superpowers/specs/2026-05-03-bl8-trash-detection-design.md). Status header v stubu se aktualizuje samostatně.

**Out of scope (explicit forward-compat notes pro BL-9 candidate):**
- Trashed `status='failed'` / `status='skipped'` rows — DB hygiene, žádné lokální soubory k mazání.
- Plaud auto-purge (Plaud's own retention) — pokud Plaud purgne před PlaudSync detection, DB row stays `'downloaded'`, files orphan. Reconciliation pass (DB ∪ active ∪ trashed) by byl plný BL-9 scope.

**Kill criteria delta:** žádné triggernuté. Bug class byl architectural gap (PlaudSync neměl signal mechanism pro Plaud-side state mutations) — preventivně shipnuto před prvním real incidentem. `_TRASH_BATCH_ABSOLUTE`/`_TRASH_BATCH_RATIO` jako hard-coded je explicitně volitelná pozice (kill criterion #19 dynamic surface), ne config flag — pokud false-positive guard trip nastane reálně >2×, zvážit konfiguraci.

Backlog stav: BL-1 (progress bar), BL-5 (2 sub-cases open: folder-move detection + content drift), BL-6 (shipped), BL-7 (shipped), BL-8 (shipped). 1 active stub (BL-1) + 2 BL-5 sub-cases + 1 BL-9 candidate (orphan reconciliation, žádný stub yet).

---

## 2026-05-03 — BL-7 shipped (surface ignored recordings)

Implementace BL-7 stubu z 04-30. Skip-source nahrávky (`outcome.source == "skip"` — žádná strategie nematchla + `sync_unclassified=false`) už nejsou silently dropped — persisují do `recordings` tabulky se `status='skipped'` + `classification_source='skip'`.

**Decision lock:** reuse `'skipped'` status + nový discriminator `classification_source='skip'` (doporučená cesta z stubu §3). Žádná schema migration; existing CHECK constraint pokrývá `'skipped'` a `classification_source` je nullable TEXT z BL-X.

**Recovery paths (BL-7 stub §6 edge cases):**
- Project added to config + Plaud rename → main loop natural re-process via `recording_exists_and_downloaded` (vrací False pro skipped) → `_process_recording` reclassifuje a Hotfix L upgrade `skipped → downloaded` triggeruje UPSERT.
- `sync_unclassified=true` flip → main loop natural re-process → catch-all kicks in → upgrade na `downloaded` se `source='none'`.
- Žádné rozšíření retry passu nebylo potřeba (na rozdíl od stubu doporučení §6.1) — main loop iteruje all live metas, dedup jen na `status='downloaded'`, takže skip-source rows se přirozeně re-processnou každý sync.

**Files touched:** `src/plaudsync/sync.py` (`_process_recording` skip větev), `src/plaudsync/ui/state_reader.py` (`'skip'` v Literal type), `frontend/src/api/types.ts` (`ClassificationSource` union), `frontend/src/pages/Dashboard/ProjectBadge.tsx` (gray "ignorováno" pill + tooltip). Mock state extended s rec_007 pro DevPanel ověření.

**Tests:** `tests/test_bl7_surface_ignored.py` — 6 cases: skip persistence, NULL folder ID handling, project-added upgrade, sync_unclassified flip upgrade, state_reader wire payload, FiletagCache folder name resolve. Update 2 pre-existing tests (`test_waterfall_skip_writes_no_db_row` → `test_waterfall_skip_persists_row_no_audio`, `test_sync_unclassified_off_drops_unknown_then_on_picks_up_new`) — assertovaly starou silent-drop semantic.

**LoC odhad vs. realita:** stub §7 odhadl ~80 LoC + 6 tests; reálně ~30 LoC backend + ~20 LoC frontend + ~290 LoC test (includes copy of fake client harness). 6 nových testů + 2 updated.

Backlog stav: BL-1 (progress bar), BL-5 (2 sub-cases open), BL-6 (badge — shipped), BL-7 (shipped), BL-8 (trash detection — pending soak/incident trigger).

---

## 2026-04-30 — BL-7 + BL-8 stubs (UI completeness gaps)

User otázka: „Můžu se spolehnout, že se v seznamu nahrávek zobrazují všechny? Jsou některé vyřazené apriori? Jak je to s těmi v koši?"

Tři a-priori filtry surfacovaly:
1. **`is_trash=0` v listing call** — trashed recordings nikdy nestaženy.
2. **`outcome.source == "skip"`** — žádný klasifikační signal + `sync_unclassified=False` → no DB row → invisible.
3. **`LIMIT 50`** v state_reader pagination (UI scroll/pagination not implemented).

**Stubs filed:**

- [BL-7](docs/superpowers/specs/2026-04-30-bl7-surface-ignored-recordings-stub.md) — surface ignored (skip-source) recordings in UI as gray pill so user has signal that PlaudSync saw them but had no strategy. Decision to lock: new `'ignored'` enum value vs. reuse `'skipped'` + source='skip' discriminator. Recommended: reuse (no schema migration). ~80 LoC + 6 tests.
- [BL-8](docs/superpowers/specs/2026-04-30-bl8-trash-detection-stub.md) — dedicated subset of BL-5 (carved out from rename + folder-move + content-drift). Detects trashed recordings via separate `is_trash=1` listing call. Decisions: trash policy (hard / archive / mark), untrash recovery, UI strikethrough. ~150 LoC backend + 50 LoC frontend.

**Trigger conditions:**
- BL-7: independent of others, ship anytime. Soft prereq BL-6 (badge styling).
- BL-8: 3 trash incidents in 30 days OR 14d post-BL-X soak (extended from BL-5's 7d due to hotfix-storm).

Backlog stav po dnešku: BL-1, BL-5 (rename shipped, 2 sub-cases open), BL-6 (badge UI), BL-7 (ignored visibility), BL-8 (trash detection). 4 active stubs + BL-1 progress bar.

---

## 2026-04-30 — Test gap audit + Hotfix M (classification_source persist on reclassify)

**Trigger:** User question „Jak to, že nebylo pokryto testy?" po Hotfix L. Šel jsem systematicky napříč state machines + config flags hledat podobné gaps.

**Audit scope:**
1. `recordings.status` transition matrix (4×4 = 16 cases)
2. Config flag round-trip (toggle on→off→on) pro každý mutable flag
3. `classification_source` transitions (name↔folder via Plaud rename)
4. `content_status` round-trip (pending↔complete via partial emit, Hotfix H)

**25 nových testů:**

`tests/test_state_upsert_matrix.py` (17 testů):
- `test_upgrade_to_downloaded_succeeds[failed/skipped/skipped_unknown_project]` — všechny 3 upgrade paths.
- `test_downloaded_is_sticky_against_all_incoming[*]` — 4 cases verifying immutability.
- `test_failure_to_failure_is_noop[*-*]` — 9 cases (3×3) verifying non-upgrade transitions preserve original.
- `test_idempotent_reinsert_skipped` — same status twice = noop.

`tests/test_config_roundtrip.py` (5 testů):
- `test_download_audio_off_then_on_upgrades_skipped_to_downloaded` — Hotfix L scenario (production replay).
- `test_download_audio_on_off_on_full_round_trip` — 3-step cycle, downloaded sticky against off.
- `test_download_content_off_then_on_writes_md_on_second_sync` — **odhalil další known gap** (not_applicable nepřejde na pending při re-enable; documented, ne fix-uto teď).
- `test_classify_by_folder_off_then_on_recovers_skipped_unknown_project` — Hotfix I retry path.
- `test_sync_unclassified_off_drops_unknown_then_on_picks_up_new` — catch-all toggle.

`tests/test_classification_source_transitions.py` (3 testy):
- `test_classification_source_folder_to_name_after_plaud_rename` — folder→name via Plaud rename. **Odhalil Hotfix M bug** — `_reclassify_recent` UPDATE neprosadí classification_source.
- `test_classification_source_persisted_when_label_unchanged` — title-only edit, source stays correct.
- `test_classification_source_unchanged_for_idempotent_resync` — idempotent sanity.

**Hotfix M (commit `<this commit>`):** `_reclassify_recent` SQL UPDATE doplněn o `classification_source = 'name'` (NameClassifier-only path; folder source je v WaterfallClassifier mimo tento retry pass). Jiný silent UI-cosmetic bug analogous to Hotfix K — folder/name source mismatch v DB by způsobil špatnou barvu BL-6 badge.

**Lessons learned codified:**

| Pattern | Test added |
|---|---|
| State enum upgrade transitions | UPSERT matrix (16 cases parametrized) |
| State immutability (downloaded sticky) | 4 cases verifying preservation |
| Config flag round-trip | 5 toggle scenarios |
| Classification source transitions | 3 cases |
| New column added to schema | (audit checklist below) |

**Audit checklist pro budoucí změny schema (codified for future BLs):**
- ✅ Existující `record_recording` UPSERT include nové kolonu v INSERT path?
- ✅ Existující `record_recording` UPSERT include novou kolonu v UPDATE path? (Hotfix L gap)
- ✅ `_reclassify_recent` UPDATE include novou kolonu? (Hotfix M gap)
- ✅ `_retry_skipped_unknown_project` UPDATE include novou kolonu? (Hotfix K gap)
- ✅ `_retry_pending_content` UPDATE include novou kolonu?
- ✅ Test pro round-trip: write → re-write → verify column updated.

Tato checklist je třeba aplikovat **PŘED** merge nového sloupce / status hodnoty. Budoucí hotfix-storm prevention.

**Tests:** 389 → 414 (+25). 12 hotfixů + audit dnes.

---

## 2026-04-30 — BL-4 prod hotfix L (status='skipped' rows can't upgrade to 'downloaded')

**Symptom:** User toggle-oval `download_audio=False` v 12:08-12:20 (testoval Settings), 2 recordings (`04-30 FHB: Rozšíření webhooků`, `04-30 Alza: orientace klecí`) byly synced jako `status='skipped'`. Po user-toggle download_audio=True zpět + Sync Now zůstaly recordings stále `status='skipped'`. UI ukazuje rotating arrow icon (skipped state) místo zeleného check.

**Layer:** Layer 4 — DB persistence UPSERT logic.

**Root cause:** `state.py::record_recording` UPSERT branch:
```python
elif existing[0] in ("failed", "skipped_unknown_project") and status == "downloaded":
    # UPDATE
```
Status `'skipped'` (BL-X audio gate decline) **chybí** v upgrade-able seznamu. Když row je `'skipped'` a sync chce zapsat `'downloaded'`, padá to do else=noop branch → row stuck.

**Test gap (post-mortem na user otázku „Jak to, že nebylo pokryto testy?"):**
- BL-X Task 14 přidal test `test_download_audio_false_records_skipped_status` (jeden směr).
- Druhý směr — `existing=skipped, incoming=downloaded → UPDATE` — chyběl.
- Klasický „untested round-trip" pattern. Test pokrývá *vstup do stavu* ale ne *výstup ze stavu*.
- Existující `test_record_recording_upgrades_skipped_to_downloaded` v `test_state_migrations.py` testoval jen `skipped_unknown_project`, ne nový BL-X 'skipped' význam.

**Systémová chyba — proč to neproshlo audit:**
- 10 hotfixů na BL-4/BL-X v jednom dni (A→L) signalizuje že ship rychlost překonala reálnou test maturity.
- Většina nových testů jsou happy-path; **config-mutation scenarios** (toggle on→off→on) systematicky pod-pokryté.
- Žádný formální state machine diagram pro `recordings.status` enum.

**Fix (commit `<this commit>`):** Přidat `'skipped'` do elif upgrade-able statuses. + Test `test_record_recording_upgrades_skipped_to_downloaded` pro nový BL-X význam.

**Tests:** 388 → 389 passing.

**Impact na produkci:** Po Sync Now 2 stuck rows (`c1059621` FHB, `014ec19e` Alza) projdou main loop, `recording_exists_and_downloaded` returns False (status='skipped'≠'downloaded'), `_process_recording` zavolá `record_recording(status='downloaded')`, fix kicks in → UPDATE → MP3 sjede + .md generated.

**Severity:** P2. UI signal že feature je rozbitá, ale data nejsou poškozená — re-sync to opraví.

**Action items:**
1. **State transition matrix test** — parametrized test pro všechny `(existing, incoming) → outcome` kombinace. Cca 16 cases. (BL-7 ticket?)
2. **Two-step config-change test pattern** — pro každý config flag toggle on→off→on round-trip.
3. **Audit při každém novém status enum value** — `state.py::record_recording` + tests.

11 hotfixů celkem dnes na BL-4/BL-X. Eskaluje urgentnost stress-test review po cool-down.

---

## 2026-04-30 — BL-4 prod hotfix K (retry pass missed plaud_folder_id persistence)

**Symptom:** CPR row se po Hotfix I retry-pass folder fallback objevil v UI s badge `(neznámá složka)` přestože folder NÁZEV (`Školení`) byl správný a v filetag_cache existoval.

**Layer:** Layer 4 — DB persistence path. Sync engine logic OK, UI lookup OK, ale persistence vrstva mezi nimi kapsla folder ID.

**Root cause:** `_retry_skipped_unknown_project` UPDATE SQL při Hotfix I folder fallback zapsal `classifier_label='Školení'` + `classification_source='folder'`, ale **nezahrnoval `plaud_folder_id`**. UI state_reader resolve folder name přes `filetag_cache.lookup_by_id(plaud_folder_id)` — pro NULL ID returnuje placeholder.

**Fix:** retry pass UPDATE rozšířen o `plaud_folder_id` column. Zdroj hodnoty: `live_meta.plaud_folder` (Hotfix J extracted real folder ID from filetag_id_list). Když retry pass použije folder fallback, `row_folder_id` má hodnotu Plaud folder ID z listingu.

**Tests:** 388 passing (no new tests — pure DB persistence fix, integration covered by existing `test_sync_retry_skipped_live_title` patterns).

**Impact na produkci:** 2 production rows backfill-ed manuálně přes SQL (`UPDATE recordings SET plaud_folder_id=... WHERE classification_source='folder' AND plaud_folder_id IS NULL`). Mapping z config.projects[label].plaud_folder_id. Rows se klasifikací 'folder' co měly NULL ID teď mají správný folder_id → UI badge resolve-uje folder name.

**Severity:** P2. UI cosmetic problem (badge text), ale signal že Hotfix I path nekompletní.

---

## 2026-04-30 — BL-4 prod hotfix J (folder ID extraction was DEAD since BL-X)

**Symptom:** User filed recording `04-30 Strategický rozpor mezi evidencí a monitoringem hardwarových prvků` do Plaud folder Alza.sk. ALZA project má v configu folder mapping na `8ed7ab6e5a68f02e31f736a15a99024d` (Alza.sk). filetag_cache catalog OK. classify_by_folder=True. Přesto recording NEPŘILETĚL — DB row neexistuje vůbec.

**Layer (per `sync-debug` skill):** Layer 3-ish — API contract drift. Mezi spike (cassette test) a production listing.

**Root cause (commit `<this commit>`):** `RecordingMeta.from_raw` četl Plaud listing pole `raw.get("filetag_id")` (singular) jako zdroj folder ID. Plaud API ale vrací **`filetag_id_list`** (LIST). Pole `filetag_id` ve skutečném response **neexistuje**. Důsledek: `plaud_folder = None or "_unknown"` pro VŠECHNY recordings — od BL-X šipu napříč produkční DB.

**Proč to nikdo nezpozoroval do dnes:** všechny dosud zpracované recordings měly title formát `MM-DD KOD:` → name regex match → klasifikace přes name strategy. Folder strategy se nikdy nevolala s real folder ID (vždy dostala `_unknown`). Tvůj Strategický rozpor recording je první real-world test of folder path — bez `:` v titulu je name strategy mrtvá → folder má všechen vliv → Hotfix J bug fired.

**Fix:** `RecordingMeta.from_raw` reads `filetag_id_list[0]` (preferentně), s fallbackem na `filetag_id` (singular) a `tag_ids[0]` pro defensive backward-compat. Empty list / missing key → `_unknown` (existing semantic).

**Tests:** 381 → 388 passing, +7 v `tests/unit/test_recording_meta_filetag.py` pokrývající: filetag_id_list extraction, empty list, missing key, multi-entry first-wins, legacy singular field, legacy tag_ids field, precedence order.

**Impact na produkci:**
- Strategický rozpor recording: po next Sync Now sjede do `Recordings/ALZA/` přes folder source. Žádný DB cleanup needed (recording v DB neexistoval).
- Existing rows: žádné nejsou impacted, protože všechny stávající rows byly name-classified (jejich classification stále valid). Folder classifier teď začne fungovat pro budoucí recordings + retry pass legacy stuck rows.

**Kill criteria check:** **#19 (folder coverage <30 %) byl jako kritérium až dnes nepoužitelný** — folder coverage byla 0 % skrz celý BL-X! Po Hotfix J konečně bude relevantní telemetrie. Resetuju 60d window pro #19 začátek od dneška.

**Severity:** P1. Folder klasifikační strategie byla v produkci celou dobu **inert** — uživatel s `classify_by_folder=true` měl false sense že to funguje. 9 hotfixů tento týden + tento je nejvíce závažný (silent feature failure).

---

## 2026-04-30 — BL-4 prod hotfix H + I (partial-emit + name→folder fallback)

**Symptoms (sequenced):**

1. User: `04-30 OEZ: Úprava layoutu` (30:42 dlouhý, ~7.8 MB) má `content_status='pending'`, žádné .md. DB row `task_ids = {trans, outline}` (chybí summary). Plaud queue task IDs progresivně — `summary_id` ještě nedoplnil → row v pending limbu.

2. User: `04-28 CPR: Terapeutické rodičovství` má badge "CPR" (modře, name source) přestože CPR není v configu. Recording je ve složce "Školení" na Plaude (Školení MÁ folder mapping v configu) — user očekával "Školení" badge zeleně.

**Root cause #1 (Hotfix H, content_fetcher.py):** All-or-nothing emit semantic. Když Plaud nedotvořil VŠECHNY 3 typy (transcript + outline + summary), .md se nepsal. User čekal i 2+ hodiny.

**Fix H:** per-section readiness — emit partial .md jakmile alespoň 1 sekce ready. Status='pending' s ready sekcemi → caller writes partial .md, retry pass overwrites při příštím sync až další sekce přibudou. Když Plaud nakonec dotvoří summary, .md má všech 3 sekce.

**Root cause #2 (Hotfix I, classifier.py):** WaterfallClassifier returnoval `(label="CPR", source="name")` při name-regex match na "CPR" — i když CPR není v configu. BL-3 gate v sync.py skipnul recording jako `skipped_unknown_project`, NIKDY se nepokusil folder fallback (Školení folder mapping ignored).

**Fix I:** WaterfallClassifier — když name match produkuje project NOT in config AND classify_by_folder=True AND folder mapping existuje → použít folder source. Když folder fallback nematched → vrátit name label se source='name' (BL-3 retry path zachován pro pozdější config update).

`_retry_skipped_unknown_project` taky rozšířen o folder fallback pro legacy stuck rows.

**Tests:** 363 → 381 passing. +6 v `test_content_fetcher.py` (partial emit), +4 v `test_waterfall_classifier.py` (Hotfix I fall-through), updated 2 v `test_sync_retry_pending_content.py` (partial semantic), updated 1 v `test_sync_waterfall_integration.py`.

**Impact na produkci:**
- 18 skipped_unknown_project rows DELETED (`DELETE FROM recordings WHERE status='skipped_unknown_project' AND (local_path IS NULL OR local_path = '') AND created_at_plaud >= '2026-04-16'`). Ty co mají folder mapping budou re-klasifikovány Hotfix I waterfall jako folder source. Ty bez folder mappingu se znova zaepí jako skipped_unknown_project (BL-3 retry pass čeká na config update).
- `04-30 OEZ layoutu` row zůstal v pending — Hotfix H ho při příštím sync emituje s tím, co je ready (transcript + outline). Až Plaud dotvoří summary, příští retry pass ho doplní.

**Kill criteria check:** Žádné triggered. Watchpoint pro #19 (folder coverage): Hotfix I zvyšuje fold-classified rate na úkor name-classified. Telemetrie po 7 dnech ukáže effect.

**8 hotfixes na BL-4/BL-X v jednom dni** (A/B/C/D/E/F/G/H/I). Indikuje fragile feature surface — BL-5 trigger conditions extends z 7d → 14d post-stable.

---

## 2026-04-30 — BL-4 prod hotfix G (revert not_applicable eligibility — too aggressive)

**Symptom:** User report — `04-30 OEZ: Úprava layoutu...` (30:42 dlouhý, ~7.8 MB) má `content_status='not_applicable'` a chybí `.md`. Audit ukazal: 8 rows v `not_applicable`, z toho 7 jsou velké recordings (2-23 MB, real meetings) které by transcript MĚLY mít. Pouze 1 (`531fb257`, 25 KB ~1.5s) je legitimní (Plaud genuinely netranscribed).

**Layer (per `sync-debug` skill):** Layer 4. Hotfix D rozhodl o eligibility příliš tvrdě.

**Root cause (commit `<this commit>`):** Hotfix D (commit `242de91`) interpretoval subset of task_ids (méně než 3 z {trans, outline, summary}) jako `not_applicable` — assumption že Plaud nikdy nedoplní zbytek. Skutečnost: Plaud queue-uje task IDs **progresivně** (po sobě, jak ingest pipeline postupuje). Sync běžící krátce po uploadu vidí jen některé IDs → row uzamčen v `not_applicable` final, žádný retry, i když Plaud do hodiny dotvoří všechny 3.

**Fix:** Subset of task_ids missing → `pending` (was: `not_applicable`). Stejné pro empty task_ids dict. Jediná cesta do `not_applicable` je teď `_retry_pending_content` 14d stale path — pokud Plaud do 14 dnů nedotvoří, Sentry alert + status flip. Cost: tiny clips (<10s) co Plaud genuinely neprocesuje churnou v retry pass 14 dnů, pak transition. Acceptable — bound je nahoře 14d * hourly = ~336 detail calls per row.

**Tests:** 368 passing. Existující 4 tests v `test_content_fetcher.py` + 1 v `test_sync_retry_pending_content.py` updated z `not_applicable` na `pending` expectation. Žádný nový test (semantic rollback Hotfix D, no new code paths).

**Impact na produkci:** 6 rows (z 7 large) flipnuto z not_applicable → pending. SQL: `UPDATE recordings SET content_status='pending' WHERE content_status='not_applicable' AND content_path IS NULL AND created_at_plaud >= '2026-04-16' AND file_size > 100000`. The 25 KB "test 4" row záměrně **nezahrnut** (skutečně legitimní not_applicable). Po next Sync Now retry pass re-fetchne 6 rows; ty co Plaud už dotvořil → complete + .md generated.

**Kill criteria check:** Žádné triggered. Hot-path observability — kill criterion #19 (folder coverage) measurement zůstává OK; content_status nemění classification_source. Watchpoint: pokud 14d stale alert začne pálit > 5× za týden, indikuje že eligibility logika potřebuje další tuning (nutí Plaud-API-introspection pro přesnější signal).

**BL-4/BL-X total bug count today (post-deploy):** A+B+C, D, E, F, G = **7 hotfixes** v jednom dni. Indikuje že 30-day soak zóna z BL-5 stub trigger condition by měla začít teprve **po stabilizaci** — odložit BL-5 brainstorm trigger až po 7 consecutive days bez nového hotfixu.

---

## 2026-04-30 — BL-4 prod hotfix F (Plaud-side rename of downloaded rows)

**Symptom:** User na Plaude přejmenoval recording z `04-30 Test: Úprava procesu picking finish` na `04-30 OEZ: Úprava procesu picking finish`. Po Sync Now DB row stále `classifier_label='Test'`, oba MP3 i `.md` zůstaly v `Testy/`. Očekávané: oba soubory v `OEZ/`.

**Layer (per `sync-debug` skill):** Layer 4 — sync flow. Předjímáno v BL-5 stub jako "rename detection of already-downloaded rows".

**Root cause (commit `<this commit>`):** `_reclassify_recent` filtroval `classifier_label='_unclassified' AND status='downloaded'` — re-evaluoval jen unclassified rows. Downloaded rows s konkrétním project labelem (Test, ALZA, …) byly imune proti Plaud-side rename. To je užší podmnožina BL-5 scope (rename detection); zbytek BL-5 (folder move, trash) zůstává mimo scope.

**Fix:** Rozšíření `_reclassify_recent`:
- SELECT zahrnuje VŠECHNY downloaded rows v 14d window (ne jen _unclassified).
- Z `live_metas` dictu (pre-fetched v `run_sync`) čte živý title pro každou plaud_id.
- Skip work na hot-path: `current_label != "_unclassified" AND not title_changed` → nic se nedělá.
- Pokud title změněn → re-classify s effective_title; pokud nový label != current_label a je v configu → move MP3 + .md sourozenec do nového project dir + update DB (label, local_path, content_path, **title**).
- Pokud title změněn ale label se nezmění (rename within same project) → persist title to DB jen.
- Pokud nový label není v configu → leave row alone (BL-3 retry path picks up after user adds project).

Filename slug **neměníme** — soubor zůstává s původním slugem (např. `2026-04-30_04-30_Test_...mp3` po renameu na OEZ). Stabilita > slug consistency. Test `test_reclassify_skips_when_target_path_exists` by jinak selhal.

**Tests:** 363 → 368, +5 nových v `tests/test_sync_reclassify_rename.py` pokrývající:
- Plaud rename Test→OEZ → MP3 + .md move + DB update.
- Rename within same project (Test→Test) → no move, title persisted.
- Rename to project not in config → no move, label stays.
- No title change → cheap skip.
- Legacy _unclassified path → still works.

**Impact na produkci:** User-reported recording (`fb94db93...`, picking finish) automaticky přesunuto při příštím Sync Now. Žádný manual cleanup needed.

**Kill criteria check:** Žádné triggered. Kill criterion #19 (folder coverage) measurement nepostiženo — `classification_source` nemění se při name-only re-classify (zůstává `'name'`).

**BL-5 stub:** Aktualizovat — rename detection částečně shipped v hotfix F. Zbývající scope: folder move detection (classification_source='folder'), trash detection, content drift via task_id_info fingerprint compare. Zatím nedotčeno; spec stub stále platný pro tyto 3 sub-cases.

---

## 2026-04-30 — BL-4 prod hotfix E (outline + transcript JSON → markdown)

**Symptom:** Po hotfix D + Sync Now začaly vznikat `.md` sourozence, ale uvnitř obsahovaly raw JSON pole pro Outline a Transcript sekce. User otevřel soubor a viděl `[{"start_time":1240,"end_time":20930,"topic":"Úvod a e-maily"}, …]` místo čitelného markdown.

**Root cause (commit `<this commit>`):** Plaud's `content_list[].data_link` pro `outline` a `transaction` (transcript) typů vrací **JSON arrays** stringified, ne markdown. `auto_sum_note` (summary) naopak vrací plain markdown — funguje OK passthrough. ContentFetcher dotekal raw JSON do .md beze zpracování.

**Fix:** Nový modul `content_formatter.py` s per-section formatters:
- `format_outline(json_str)` → `- **MM:SS** Topic` bullet list
- `format_transcript(json_str)` → speaker turns block:
  ```
  **Speaker** [MM:SS]
  Content here.
  ```
  Consecutive same-speaker turns merged do jednoho bloku (Plaud splituje na sentence-level).
- `format_section(kind, raw)` dispatch s passthrough fallback.

ContentFetcher.fetch_artifacts teď volá `format_section` po `download_content_text` — sections dict má už hotový markdown když dorazí do compose().

Failure mode: invalid JSON nebo unexpected shape → return raw input (additive change, sync nespadne).

**Tests:** 341 → 363 passing, +22 nových v `tests/unit/test_content_formatter.py` pokrývající: timestamp formatting (s/m/h/0/negativní/invalid), outline rendering + edge cases, transcript speaker grouping + edge cases, format_section dispatch.

**Impact na produkci:** 7 already-rendered `.md` rows v DB byly stuck v complete s broken JSON content. One-shot SQL flipnul je zpět na pending (`UPDATE recordings SET content_status='pending' WHERE content_status='complete' AND content_path IS NOT NULL AND created_at_plaud >= '2026-04-16'`). Next Sync Now retry pass přerenderuje s nově formatted obsahem (overwrites existing .md atomicky).

**Kill criteria check:** Žádné triggered. Watchpoint: pokud Plaud změní schema (např. přidá pole `language` per turn), formatter graceful-degraduje na raw passthrough — pre-existing fields stále renderují.

---

## 2026-04-30 — BL-6 stub: source-aware recording badge

**Spec:** [docs/superpowers/specs/2026-04-30-bl6-recording-badge-source-aware-stub.md](docs/superpowers/specs/2026-04-30-bl6-recording-badge-source-aware-stub.md).

**Problem:** Today's Dashboard ProjectBadge shows colored badge pro každý matched recording bez ohledu na `status`. Skipped / failed rows zobrazují project code, jako by byly úspěšně staženy. Plus folder-classified recordings ukazují project code, ne Plaud folder name — user nevidí, že klasifikace přišla z folder fallback.

**Desired:**
- Badge visible ONLY pro `status='downloaded'`.
- Badge text: project code (source='name') NEBO Plaud folder name (source='folder') NEBO „nezatříděno" (source='none' / unclassified).

**Scope:** ~100 LoC + 8 tests. Backend: nový sloupec `recordings.plaud_folder_id` + 2 fields ve wire modelu (`classification_source`, `plaud_folder_name` resolved via filetag_cache). Frontend: ProjectBadge gates on `status`, větví podle `source`.

**Dependencies:** žádné — `classification_source` a filetag_cache už v place od BL-X. Lze rozjet kdykoli; nezávislé na BL-5.

**Trigger to start:** uživatelská UX preference. Ne blokujicí correctness.

---

## 2026-04-30 — BL-4 prod hotfix D (eligibility via task_id_info)

**Symptom:** Po deploy A+B+C (commit `6c74d50`) FHB recording z 04-30 přitekl jako MP3, ale `.md` sourozenec chyběl. DB row měl `content_status='not_applicable'` + `content_task_ids=NULL`. Recording 14:27 dlouhý, evidentně Plaud měl co transcribovat.

**Layer (per `sync-debug` skill):** Layer 4. ContentFetcher.fetch_artifacts logic.

**Root cause (commit `242de91`):** ContentFetcher rozlišoval pending/not_applicable podle přítomnosti všech required `data_type` v `content_list`. Pro čerstvý recording (sync ~1h po uploadu) Plaud ještě negeneroval všech 6 summary types — `transaction` byl ready, ale `outline` + `auto_sum_note` ještě ne v content_list. Pre-fix logika to označila jako `not_applicable` (final, no retry) místo `pending` (retry within 14d).

**Fix:** použít `extra_data.task_id_info` jako eligibility signál — Plaud vždy queue-uje všech 3 task IDs (trans + outline + summary) hned při ingest pro recordings, které půjde plně zprocesovat. Subset = recording ineligible (moc krátký / Plaud skipl) = legitimate `not_applicable`. Všechny 3 task IDs queued + content_list missing/pending = mid-generation = `pending`.

**Impact na produkci:** 11 DB rows bylo stuck v `not_applicable` kvůli tomuto bugu. One-shot SQL UPDATE flipnul je na `pending` aby je retry pass znovu zkusil. Žádná migrace v state.py — recovery one-time, ne ongoing.

**Test delta:** 339 → 341 passing. 1 test deleted (`test_missing_required_type_returns_not_applicable` — semantic obrácený), 3 new (eligibility subset, pending+missing-types, pending+empty-content-list).

**Kill criteria check:** Žádné triggered. Highlight: kill criterion #19 (folder coverage) telemetrie závisí na content emission rate — tento fix významně ovlivní její baseline. Watch.

---

## 2026-04-30 — BL-4 prod hotfix A+B+C (Plaud-side mutations) + BL-5 stub

**Symptom:** Den po BL-4/BL-X ship 3 expected recordings (2× FHB, 1× OEZ-renamed-from-Konzultace) nesynchronizovány lokálně, přestože byly viditelné v Plaud UI. Plus 5 default-named recordings (`2026-04-29 08:14:23` formát) stuck v `skipped_unknown_project` s nesmyslnými labels (`08`, `10`, `11`, `14`, `19` — hodina jako project name).

**Layer (per `sync-debug` skill):** Layer 4 — kategorizace + sync flow. Layers 1-3 clean (token OK, listing OK, cassette tests green).

**Three root causes (commit `6c74d50`):**

1. **Fix A — Plaud-side rename invisibility:** `_retry_skipped_unknown_project` četl DB title pro re-classify. Při Plaud rename retry pass loop-oval na stale title forever. Fix: pre-fetch listing v run_sync, předat `live_metas` dict do retry pass, classify proti live title + persist live title v UPDATE.
2. **Fix B — delayed-upload miss:** `since=last_successful_sync.finished_at` filtr v `list_recordings` filtroval podle Plaud `start_time` (= recording start, NE upload time). Recording uploaded after sync but with earlier start_time was permanently missed. Fix: drop `since` filter úplně; existing `recording_exists_and_downloaded` dedup keeps cost bounded (~5-20 pages per sync for typical accounts).
3. **Fix C — pure-digit project regex false positive:** Plaud's default file_name `YYYY-MM-DD HH:MM:SS` matched regex with project=`HH`. Fix: post-match guard `any(ch.isalpha() for ch in project)` — pure digits → unclassified.

**Test suite:** 331 → 339 passing (+ 8 new TDD-first regression tests).

**Kill criteria delta:** none triggered. Bug class was test-blind (regex on real-world default-named titles, retry-pass DB-vs-live mismatch). Adds rationale for BL-5 prioritization.

**BL-5 stub written:** [docs/superpowers/specs/2026-04-30-bl5-resync-mutations-stub.md](docs/superpowers/specs/2026-04-30-bl5-resync-mutations-stub.md). Captures requirements + 6 decision points + architecture sketch for re-sync of *already-downloaded* rows (rename/move/trash/content drift). Trigger to start: 3 incidents in 30 days OR 30-day post-BL-4 soak complete. Not before — premature scope expansion risk.

---

## 2026-04-29 — BL-4 + BL-X shipped (text artefakty + multi-layer classifier waterfall)

**Spec:** [docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md](docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md).
**Plan:** [docs/superpowers/plans/2026-04-29-bl4-bl-x-content-classifier.md](docs/superpowers/plans/2026-04-29-bl4-bl-x-content-classifier.md).

**Co se změnilo:**
- **BL-4 (text artefakty):** `.md` sourozenec MP3 obsahuje YAML frontmatter + Summary → Outline → Transcript sekce. Generuje se až všechny 3 Plaud `data_type` typy (transaction / outline / auto_sum_note) mají task_status=1. Pending → 14d retry pass; po 14d Sentry `content_stale` alert.
- **BL-X (classifier redesign):** single-layer regex → 3-strategy waterfall: name regex (s volitelným `require_folder` sub-flagem) → folder ID lookup z Plaud `/filetag/` → catch-all unclassified. `sync_only_foldered` flag eliminován; subsumed do nového `classify_by_name_require_folder` + `sync_unclassified`.
- **Settings UI delta:** WHAT × WHEN model — `download_audio` / `download_content` (artefakty) + 3 classifier strategy flags. Projektová tabulka rozšířená o `plaud_folder_id` (dropdown z `GET /api/folders`, manuální refresh přes `POST /api/folders/refresh`).
- **DB schema delta:** 4 nové sloupce v `recordings` (`content_status`, `content_path`, `content_task_ids`, `classification_source`); idempotentní ALTER TABLE migrations.
- **Privacy hardening:** observability `_scrub_string` strip-uje `*amazonaws.com` URL (signed S3 capability tokens) + truncates strings > 500 chars (defense vs. f-string transcript leak).
- **Forward-compat BL-5:** `content_task_ids` JSON snapshot uložen v DB při každé content emission → BL-5 fingerprint compare může ho porovnat s `extra_data.task_id_info` při re-sync.

**Spike outputs (committed s `69bc6f6`):**
- [scripts/spike_bl4_fields.py](scripts/spike_bl4_fields.py) — 6 `data_type` hodnot v `/file/detail/{id}` content_list; embeddings nikdy ne (voice biometric PII)
- [scripts/spike_bl_x_folders.py](scripts/spike_bl_x_folders.py) — `GET /filetag/` (note trailing slash) je folder catalog; vyžaduje `app-platform: web` + `edit-from: web` headers

**Kill criteria delta:**
- **#19 NEW:** folder-classify větev klasifikuje < 30 % recordings po 60d → revize folder vrstvy (signal že většinu zachycuje regex a folder vrstva je over-engineering).

**Cassette deferral:** Tasks 2/4/5/12 (live API integration tests pro `/filetag/`, `/file/detail/{id}`, S3 content text, ContentFetcher E2E) zůstávají bez VCR cassette. Implementation + unit tests s mocked clientem hotové. Cassette session vyžaduje fresh PLAUD_API_TOKEN + manuální scrubbing aiContentHeader/embeddings/signed URLs per cassette-refresh skill.

**Token rotation (2026-04-29):** během brainstorm session uživatel nedopatřením postnul plný Bearer token do chat history v rámci DevTools investigation. Token rotated.

**Test suite:** 328 passed (296 → 328, +32 nových). 2 Windows concurrency flakes (test_progress, test_tray_scheduler_loop) pre-existing — pasují izolovaně.

**Follow-ups:**
- Cassette recording session pro Tasks 2/4/5/12 + Task 20 E2E smoke
- Frontend (React/Tailwind) implementace nového Settings layoutu — UI spec v [docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md#10-ui-settings-page-layout-textový-spec](docs/superpowers/specs/2026-04-29-bl4-bl-x-content-classifier-design.md)
- BL-5 (re-sync změn) může začít na základě uloženého `content_task_ids` snapshot

---

## 2026-04-29 — UI 500 silent: skipped_unknown_project wire model drift

**Symptom:** Dashboard ukázal overlay „Spojení s PlaudSync ztraceno — HTTP 500". `/api/healthz` → 200, `/api/state` → 500. Nic v `plaudsync.log` (uvicorn stderr nejde do Loguru).

**Root cause (Layer 4, sync-debug skill):** BL-3 přidal `status='skipped_unknown_project'` do DB schématu i sync engine ([state.py:21](src/plaudsync/state.py#L21), [sync.py:317](src/plaudsync/sync.py#L317)), ale UI wire model `RecordingRow` v [app.py:101](src/plaudsync/ui/app.py#L101) zůstal s `Literal['downloaded','failed','skipped']`. Jakmile takový řádek spadl do TOP-50 podle `created_at_plaud DESC`, FastAPI `ResponseValidationError` shodil celý endpoint. Frontend [useConnectionLost.ts](frontend/src/components/useConnectionLost.ts) pak po 3 selháních vyplil overlay.

**Fix (commit `80a410b`):** V `_read_recordings` mapping `skipped_unknown_project → skipped` před serializací. DB schema + retry pass [sync.py:148](src/plaudsync/sync.py#L148) zůstávají beze změny, frontend `RecordingStatus` typy beze změny. Failing-first integration test (commit `ea60dcf`).

**Plná suite: 246 passed** (245 → 246, +1 regression).

**Kill criteria check:**
- `#18` (Sentry scrubbing): nemá dopad — fix je čistá serialization úprava bez nových log/Sentry surfaces.

**Souvisí s `feedback_doc_cascade_exhaustivity`:** BL-3 spec change měl udělat cascade scrub i na `app.py` Pydantic Literal a `state_reader.py` TypedDict. Frontend `types.ts` `RecordingStatus` zůstává „skipped"-only OK, protože wire collapse drží kontrakt.

**Observability follow-up:** uvicorn `ResponseValidationError` jde tiše do stderr trayu (pythonw → swallowed). Zvážit: hook FastAPI exception handler do Loguru, ať podobné silent 500 příště neumřou v ti.

---

## 2026-04-27 — Log spam: schedule-skip downgrade INFO → DEBUG

**Symptom:** Aktivní `state_root/.plaudsync/plaudsync.log` rostl o ~1 440 řádků/den mimo pracovní hodiny. Každý záznam: `sync_runner:run_sync_pipeline:88 - skipping run per schedule (work_hours=False, interval=60min)`.

**Root cause:** `SchedulerThread` tickuje každých 60 s (`tick_seconds=60.0`) a delegate-uje work-hours/interval gate na `run_sync_pipeline`. Pipeline ho vyhodnotí, vyhodí `SystemExit(5)`, ale nejdřív zaloguje INFO. Mimo work hours = INFO log per minutu.

**Fix:** `sync_runner.py:88` `logger.info` → `logger.debug`. Schedule skip není aktivovatelná událost (audit přes `sync_runs` tabulku, kde se skipy stejně neukládají). Při potřebě debugu lze přepnout `PLAUDSYNC_LOG_LEVEL=DEBUG`.

**Související legacy artefakt:** smazán `C:/GitHub/PlaudSync/plaudsync.log` (8,9 MB, gitignored). Vznikl historicky předtím, než `_configure_logging` defaultoval na `state_root/.plaudsync/plaudsync.log` (commit `4fbb65b`).

**Anomálie v logu, které byly už opraveny v aktuálním kódu (potvrzeno z git historie):**
- `tray.app:on_open_log` `FileNotFoundError` — `40fa7d0` (`os.startfile` → `subprocess.Popen(notepad)`).
- `SchedulerThread: pipeline raised uncaught` `IntegrityError CHECK constraint trigger='ui'` — `d23b57f` (`"ui"` → `"ui_sync_now"`).

---

## 2026-04-27 — BL-1 + BL-2 implementace: sync progress UI + sync_only_foldered

**Spec:** [docs/superpowers/specs/2026-04-27-bl1-bl2-progress-foldered-design.md](docs/superpowers/specs/2026-04-27-bl1-bl2-progress-foldered-design.md).

**BL-2 (commit e2a105b):**
- Nový optional bool klíč `sync_only_foldered` v `config.yaml` (default `false`).
- Pre-classifier gate v `_process_recording`: `if config.sync_only_foldered and meta.plaud_folder == "_unknown": return`. Žádný DB write, žádný download — server-side změna (uživatel zařadí záznam do složky na Plaud) se přirozeně objeví v dalším syncu.
- 3 integration testy: skips_unfoldered, passes_foldered, default_false_regression.

**BL-1 (commits 5904beb, 6b5ad9e, b5be498):**
- Nový modul `plaudsync.progress` — atomický file-based progress tracking. `write_progress` / `read_progress` / `clear_progress` / `progress_path`. Atomicita přes `tempfile.mkstemp` + `os.replace`. Windows specifika: retry loop na `PermissionError` (concurrent reader-writer collision na téže cestě).
- `run_sync` rozšířen o optional `state_root` parametr (None → no-op; backward-compat). Emituje 3 fáze: `listing` (retry/reclassify/Plaud listing), `downloading` (n/total, total = `len(materialized_listing)`), `finalizing`. Listing je nově materializován do `list()` před hlavní smyčkou kvůli `total_count`.
- `state_reader.read_state_snapshot` rozšířen o optional `state_root`. Cross-check: progress se vrací jen když existuje open `sync_run`. Stale progress.json (subprocess crash) se ignoruje.
- `ui/app.py` `/api/state` propaguje `app.state.state_root` do readeru.
- 7 + 3 + 4 testy: `test_progress.py` (concurrent stress test 200 writes vs reader thread, no partial JSON observed), `test_sync_progress_phases.py`, `test_state_reader_progress.py`.

**Plná suite: 244 passed (před BL-1+BL-2: 227, +17 nových testů).**

**Kill criteria check:**
- `#5` (regex coverage): BL-2 změna dále zužuje "matched" set — recordings bez Plaud složky se nepočítají vůbec. Watch při post-deployment monitoring.
- `#18` (Sentry scrubbing): BL-2 nemá nové log/Sentry surfaces. BL-1 progress.json obsahuje jen `sync_run_id` (interní int), `phase` (enum), counts, ISO timestamp — žádné PII, žádné business labely.

**Frontend integration (mimo scope tohoto plánu):**
- React production code už v `SyncStatePayload` má `progress` field; pokud existující polling flow ho ještě nerenderuje, je to drobný frontend ticket. Backend shape je hotový.

**Follow-ups:**
- Frontend wire-up + manual smoke test v tray UI (klik "Sync Now" → progress bar viditelně tikati per recording).
- Visibility do retry/reclassify pass počtů (dnes spadají pod `listing`, akceptováno — typicky 0-2 položky).
- Dokumentace BL-2 v README / config example.

---

## 2026-04-26 — BL-3 implementace: skip unknown project codes

**Spec:** [docs/superpowers/specs/2026-04-26-bl3-skip-unknown-projects-design.md](docs/superpowers/specs/2026-04-26-bl3-skip-unknown-projects-design.md).
**Plan:** [docs/superpowers/plans/2026-04-26-bl3-skip-unknown-projects.md](docs/superpowers/plans/2026-04-26-bl3-skip-unknown-projects.md).

**Implementováno (commits 07f76c7, ede71ff, 22ee81e):**
- Pre-download gate v `_process_recording`: regex match + `config.lookup_project(label) is None` → DB row `status='skipped_unknown_project'`, žádný download. Eliminuje vznik `_unmapped_<Project>/` složek pro náhodné project kódy z titulů.
- `_retry_skipped_unknown_project` pass v `run_sync` (před `_reclassify_recent`): SELECT skipped rows mladší 14 dnů, re-evaluate proti current configu, downloaduje matched. 14d rolling window odpovídá DEV_LOG BL-3 specu.
- `record_recording` extended UPSERT: `skipped_unknown_project → downloaded` upgrade allowed (vedle `failed → downloaded`).
- Schema migration `_migrate_status_check_constraint`: rebuild `recordings` tabulky pro existující DBs (CHECK constraint nešel ALTER, rebuild via temp-table copy). Plan-defect zachycený při běhu prvního testu — fix bez eskalace per `feedback_plan_literal_vs_reviewer`.

**Test coverage (3 nové integration testy v `tests/test_sync_skip_unknown_project.py`):**
- `test_unknown_project_is_skipped_not_downloaded` — gate funguje (no download, DB row, no MP3).
- `test_skipped_recording_retried_after_config_update` — retry pass downloaduje po doplnění configu.
- `test_skipped_recording_outside_14d_window_not_retried` — cutoff respektován.

Plná suite: 222 passed.

**Kill criteria check:**
- `#5` (regex coverage <90 %): BL-3 zužuje "matched" definici — záznamy s neznámým project kódem se teď počítají jako "skipped_unknown_project", ne jako "matched". Watch monitoring metric po nasazení.
- `#18` (Sentry scrubbing): nové tagy `error_kind='skipped_unknown_project'` (info-level, no capture) a `error_kind='retry_skipped_failed'` (capture s fingerprint). Project label posíláno přes `logger.bind(project=...)`, ne v message — per CLAUDE.md privacy rules.

**Follow-ups:**
- Cleanup helper / one-off skript pro existující `_unmapped_<Project>/` složky z období před BL-3 (samostatný ticket — manuální `mv` + DB UPDATE, nebo dedicated CLI subcommand).
- UI badge "skipped: N" v tray menu pro audit (samostatný ticket).
- Stale title race v retry passu (DB title se neaktualizuje při Plaud-side rename) — pre-existing pattern stejný jako `_reclassify_recent`, neřešíme teď.
- `/review` + `/security-review` + manual smoke v tray UI — gates k uživatelskému spuštění před merge na main (jsme už na main, ale BL-3 commits jsou unpushed pro review).

---

## 2026-04-26 — Backlog: 5 nových položek k implementaci

Poznámky z uživatelského review. Žádná není blokující pro v0; zařadit do Phase 3 / Phase 4 sprintů.

### BL-1 — UI: progress bar při manuální synchronizaci

**Popis:** Po stisku tlačítka „Synchronizovat" v UI se nezobrazuje progress bar, přestože je navržen v prototypu [`frontend/_prototype/PlaudSync UI.html`](frontend/_prototype/PlaudSync%20UI.html). Uživatel nevidí průběh operace.

**Co je potřeba:** Propojit existující WebSocket/SSE stream ze sync backendu s progress komponentou ve frontendu. Prototype HTML obsahuje referenční design.

---

### BL-2 — Nastavení: synchronizovat pouze záznamy zařazené do složky na Plaude

**Popis:** Nová volba v `config.yaml` (nebo UI Settings) — `sync_only_foldered: true`. Záznamy, které na straně Plaude nejsou zařazené do žádné složky, se při synchronizaci přeskočí.

**Co je potřeba:** Analyzovat Plaud API response strukturu pro příznak složky; přidat config key + filtr v sync smyčce; doplnit test cassette.

---

### BL-3 — Kategorizace: ignorovat neznámé project kódy z názvu záznamu

**Popis:** Záznamy s tituly ve formátu `kod_projektu: ...` se mají kategorizovat pouze pokud `kod_projektu` je již definovaný v `config.yaml` pod `projects:`. Neznámé kódy se NEPŘIDÁVAJÍ automaticky — záznam jde do `Unclassified`. Toto omezení se vztahuje na starší záznamy maximálně za posledních 14 dní (rolling window).

**Co je potřeba:** Upravit `categorization.py` — po regex match ověřit `Config.lookup_project(code)` a při `None` fallback na `_unclassified`; 14d window pro starší záznamy (analogie `_reclassify_recent`). Napsat failing test jako první.

---

### BL-4 — Stahování přepisů, osnov, mluvčích a sumarizací (nejen MP3)

**Popis:** Vedle audio souboru (MP3) stahovat také textový obsah záznamu: transkript, osnova, identifikace mluvčích, sumarizace. Plaud API pravděpodobně poskytuje více typů sumarizací (krátká, detailní, action items…) — tyto varianty je potřeba nejdříve zmapovat.

**Analýza potřebná před implementací:**
1. Zdokumentovat všechny dostupné `note_type` / content fields v Plaud API response.
2. Navrhnout config volby: které typy stahovat per-projekt nebo globálně.
3. Rozhodnout formát ukládání (vedle MP3 jako `{stem}.transcript.txt`, `{stem}.summary.json` apod.).

**Co je potřeba:** Spike → API analýza → spec → TDD implementace.

---

### BL-5 — Synchronizace změn transkripce (lokální update při změně na Plaude)

**Popis:** Pokud se transkript nebo jiný textový obsah záznamu na Plaude změní po prvotním stažení, lokální soubory se mají aktualizovat. Pravděpodobně bude potřeba časové omezení (např. kontrolovat jen záznamy mladší N dní nebo porovnávat `updated_at`).

**Závislost:** Navazuje na BL-4 (stahování přepisů).

**Co je potřeba:** Přidat `transcript_updated_at` (nebo ekvivalent) do DB state; v sync smyčce porovnat s lokálně uloženou hodnotou; při rozdílu přepsat soubory. Definovat časové okno v konfiguraci.

---

## 2026-04-26 — Classifier wire-up + 14d rolling re-classify

**Symptom:** 2 recordings staženy 2026-04-26 (`04-26 Alza: test1`, `2026-04-26 FHB: test2`) skončily v `Unclassified/_unknown/` přesto, že title formát match-uje regex a project klíče v `config.yaml` (`ALZA`, `FHB`) by byly rozpoznatelné case-insensitive.

**Layer (per `sync-debug` skill):** Layer 4 — categorization. Layers 1-3 byly clean.

**Root cause:** `__main__.py:141` injectoval `DefaultBucketClassifier()` (placeholder vracející `_unclassified` vždy), ne reálný `categorization.classify()`. Sekundárně: `path_resolver` indexoval `config.projects[project]` literálně, takže i po wire-up by `project='Alza'` vs. `config_key='ALZA'` skončilo v `_unmapped_Alza/`.

**Fix:**
1. `CategorizationClassifier` adapter v `classifier.py` zabaluje `categorization.classify()` do `Classifier` Protocol shape.
2. `Config.lookup_project(name)` provádí casefold-based lookup; `path_resolver` přechází na metodu; `load_config` odmítá duplicit casefold klíče.
3. `_reclassify_recent()` pass v `run_sync()` před hlavní download loop — re-klasifikuje rows s `classifier_label='_unclassified'` a `downloaded_at >= now-14d`, fyzicky přesouvá soubory + updatuje DB. Edge cases: missing source / target collision → warning + skip; IO error → Sentry capture + failed_count++.

**Spec:** [docs/superpowers/specs/2026-04-26-classifier-wireup-design.md](docs/superpowers/specs/2026-04-26-classifier-wireup-design.md).
**Plan:** [docs/superpowers/plans/2026-04-26-classifier-wireup.md](docs/superpowers/plans/2026-04-26-classifier-wireup.md).

**Kill criteria check:**
- `#5` (regex coverage <90 %): teprve s tímto fixem se začne reálně měřit. 30-day window monitoring stále není implementovaný — watch item.
- `#18` (Sentry scrubbing): re-classify pass přidává `recording_id` tag, použité scrubbing rules ho pokryjí (existující pattern, žádný nový exposure).

**Follow-ups (z code review, plan-suboptimal stick s plánem během execution):**
- `load_config` guard against non-string YAML project keys (Task 2 review I-1).
- `path_resolver` module docstring add case-insensitive note (Task 3 review M1).
- Drop `replace("Z", "+00:00")` across 5 sites — Python 3.11 `fromisoformat` handles Z natively (Task 4 review M1).
- Drop unused `run_id` param in `_reclassify_recent` + add `logger.info` reclassify summary (Task 6 review I-1, I-2).
- `SimpleNamespace` instead of `class _MetaLike: pass` inline (Task 6 review M-1).
- Explicit Sentry-tag assertion test for `reclassify_failed` error_kind (Task 7 review M2).
- Extract `_make_reclassify_env` fixture when test file > 6 tests (Task 7 review M3).

**Verifikace dnešních 2 souborů:** automaticky se přesunou při příštím `python -m plaudsync` běhu (Task Scheduler tick nebo manual). Task 9 plánu provede manuální production run.

---

## 2026-04-26 — v0 production-ready: Schedule + Phase 2 smoke + security review + Task Scheduler installer

Single-session batch wrapping v0 to shippable. 4 commits to origin/main.

### Schedule feature merged

`feat(schedule): work-hours/off-hours sync gating + UI endpoint` (`aa8d4dc`):
- `src/plaudsync/schedule.py` (270 LoC) + 26 tests (`test_schedule.py` 22 + `test_ui_schedule_endpoint.py` 4) — all green.
- `__main__.py` schedule gating block, exit 5 on skip (same as SyncLockHeld for benign alerting).
- `ui/app.py` GET/PUT `/api/schedule` endpoints with 422 validation.

`feat(ui/settings): Schedule panel + YAML syntax highlight` (`317e58d`):
- SchedulePanel.tsx (271 LoC) + yamlHighlight.ts (136 LoC; Settings spec Gap 5 deferred → shipped).
- YamlEditor overlay rendering with `escapeHtml` first (XSS-safe `dangerouslySetInnerHTML`).

### Code review (subagent) — 3 must-fix applied pre-commit

- **C1:** dropped dead `try/except sqlite3.OperationalError` in `__main__` (open_state has CREATE IF NOT EXISTS).
- **I1:** removed unused `timezone` import.
- **I2:** `save_schedule` now atomic via `os.replace` — prevents UI/CLI race producing torn JSON read.
- **Test mock parity:** `_setup_sync_pipeline_mocks` now bootstraps `_SCHEMA` in `:memory:` connection (regression fixed).

After fixes: 155/155 tests green, bandit 0 H / 0 M / 3 L (subprocess intentional).

### Phase 2 backend smoke PASS

`python -m plaudsync ui --dev` against tmp `PLAUDSYNC_STATE_ROOT`:

| Endpoint | Status | Verified |
|---|---|---|
| `/api/healthz` | 200 | `{"status":"ok"}` |
| `/api/state` | 200 | sync=idle, recordings=[] |
| `/api/config` | 200 | UI-seeded DEFAULT_YAML (lifespan auto-seed works) |
| `/api/schedule` | 200 | defaults: 15min work / 60min off, Mon-Fri 8-16 |

Lifespan handler auto-created `config.yaml`, `.plaudsync/state.db` (+ WAL + shm).

### `/security-review` — clean

`superpowers:code-reviewer` reviewed all 3 commits. **No HIGH-CONFIDENCE findings.** Verified: dangerouslySetInnerHTML is XSS-safe (escapeHtml + closed Cls union + CSP defense), `/api/schedule` PUT validates Pydantic shape + range, `save_schedule` writes fixed path, `load_schedule` uses `json.loads` (safe), schedule gating bypass only for `task_scheduler` trigger.

### Production go-live artifacts

`docs(production): Task Scheduler installer + README setup quickstart` (`ed089fc`):
- `scripts/install-task-scheduler.ps1` — PowerShell helper, idempotent, per-user Limited token, 15-min ticks.
- `README.md` — quickstart, Plaud token recipe, Task Scheduler one-liner, data flow diagram, ops triage table.

### Pending user actions for full go-live

1. `.\scripts\install-task-scheduler.ps1` (per-user, no admin).
2. Wait 15 min OR `Start-ScheduledTask -TaskName "PlaudSync"`. Verify `<STATE_ROOT>\plaudsync.log` + Sentry.
3. Tune Schedule via UI Settings if 15-min default needs adjusting.

### Status

**v0 shippable end-to-end.** Auth + sync core + categorization + UI backend + frontend + schedule gating live on `main`. 155 tests green, bandit clean, Sentry scrubbing verified, CSP locked, no security findings.

**v1.1 backlog:** Dashboard `_unmapped_<project>` badge variant, log viewer modal, Plaud `filetag_id` UUID → display name resolution, click-row drill-down detail.

---

## 2026-04-25 — UI frontend Phase 1 smoke (mock data) PASS

Branch `feat/ui-frontend` complete: 15 plan tasks + 4 follow-up fix
commits = 19 commits total. ~25 TSX modules transcribing prototype
`frontend/_prototype/PlaudSync UI.html` (validated Claude Design
prototype) into Vite + React 19 + TS strict + Tailwind 4 project at
`frontend/`. Worktree-isolated impl path: `c:/tmp/PlaudSync-ui-frontend`.

### Phase 1 verification matrix (mock-data only, no live backend)

All 12 automated checks passed:

| Check | Result |
|---|---|
| `npm run typecheck` (TS strict, all flags) | exit 0 |
| `npm run build` end-to-end | clean |
| Bundle gzip size | **94.9 KB** (budget 200 KB; W-U2 threshold 500 KB) |
| `src/plaudsync/ui/static/` populated post-build | yes |
| Static dir gitignored (clean working tree post-build) | yes |
| No inline `<script>` in production index.html (CSP) | clean |
| Privacy grep — no business labels in toast/banner strings | PASS |
| `npm run dev` startup | VITE ready in ~300 ms |
| Dev mock layer tree-shaken from production bundle | confirmed |
| Czech localization spot-check (D10 lock) | 12 matches |
| Component file count (components/9, Dashboard/5, Settings/5, dev/3) | match |
| Commit count on branch | 19 |

### Bundle composition (gzipped)

- `assets/index-HASH.js` (app code) — 62.6 KB
- `assets/react-HASH.js` (React + ReactDOM + react-router-dom chunk) — 15.0 KB
- `assets/query-HASH.js` (TanStack Query chunk) — 10.0 KB
- `assets/index-HASH.css` (Tailwind 4 generated) — 7.0 KB
- `index.html` — 0.3 KB

### Deviations from plan resolved during execution

- **Task 1 fix:** `vite.config.ts` `__dirname` → `fileURLToPath(new URL("./src", import.meta.url))` (ESM-idiomatic; the original CJS-style worked only via Vite's internal esbuild shim).
- **Task 2 fix #1:** focus-visible block moved from unlayered into `@layer base` (lets Tailwind `ring-*` utilities override where needed).
- **Task 2 fix #2:** Tailwind 4.0.0 `@tailwindcss/postcss` had an oxide-rust scanner crash (`Missing field 'negated' on ScannerOptions.sources`); bumped tailwindcss + @tailwindcss/postcss to 4.0.17 AND migrated keyframes from `tailwind.config.ts` to CSS-native `@theme` block in `index.css`. Also moved `@plugin "@tailwindcss/forms"` registration into CSS. `tailwind.config.ts` reduced to a stub kept for IDE tooling.
- **Task 1/14:** package.json forced bumps (Vite 7 peer deps): `@vitejs/plugin-react` 4.3.4 → 5.2.0, `@types/node` 22.10.2 → 22.12.0.
- **Task 13:** added `frontend/src/vite-env.d.ts` (`/// <reference types="vite/client" />`) so tsc strict knows about `import.meta.env`. Standard Vite reference fix.
- **Task 6 chore:** appended `*.tsbuildinfo`, `vite.config.d.ts`, `vite.config.js` to `frontend/.gitignore` (tsc -b composite outputs).

### Phase 1 ACs covered

Dashboard ACs (mock-data testable): 1, 2, 7, 8, 10, 12, 13.
Settings ACs (mock-data testable): 1, 5, 14, 15, 16, 17, 18, 19, 20.

### Phase 2 ACs deferred (need live backend)

Dashboard: 3, 4, 5, 6, 9, 11.
Settings: 2, 3, 4, 5 (live verify), 6, 7, 8, 9, 10, 11, 12, 13.

### Next step

Phase 2 smoke schedule: after `feat/ui-backend` merges to master, spin
up `python -m plaudsync ui` + `cd frontend && npm run dev` with
`PLAUDSYNC_DEV_PORT=8765`, walk through deferred ACs, append Phase 2
DEV_LOG entry. **Manual `/security-review` recommended before merging
`feat/ui-frontend` to main** (CLAUDE.md "before merging to main" gate).

### Open follow-ups (not blockers, captured pre-v1.1)

- Dashboard Gap 1: `_unmapped_<project>` badge variant — needs backend
  `RecordingRow.classification_route` field (sync-core spec follow-up).
- Dashboard Gap 4: log viewer modal vs current toast-points-to-log —
  deferred to v1.1+.
- Settings Gap 5: YAML syntax highlight — deferred per spec.
- Task 4 client.ts: `{ raw: text }` fallback for non-JSON bodies could
  collide with a real `raw` JSON key; consider boxing differently in v1.1.
- Task 4 client.ts: `AbortSignal` plumbing not yet done (TanStack v5
  passes `signal` to queryFn — currently dropped). Defer to v1.1+.

---

## 2026-04-25 — UI backend implementation done + smoke test PASS

Implementation execution of `docs/superpowers/plans/2026-04-25-ui-backend.md`
via subagent-driven-development on branch `feat/ui-backend`. 28 commits
landed across 19 tasks.

**What landed:**

- 6 new modules under `src/plaudsync/ui/` (~580 LoC src + ~520 LoC tests):
  `__init__.py`, `config_io.py` (DEFAULT_YAML + read/save/seed), `state_reader.py`
  (snapshot + running queries), `sync_starter.py` (subprocess + 500ms wait),
  `app.py` (FastAPI + 6 endpoints + Pydantic models + CSP + StaticFiles),
  `runner.py` (uvicorn + PyWebView + browser fallback).
- `auth.mask_token()` helper (first_8 + 15 dots + last_4).
- `__main__.py` `ui` subcommand with `--dev` flag wiring.
- `pyproject.toml` deps: `fastapi>=0.115`, `uvicorn[standard]>=0.30`,
  `pywebview>=5.3`. Resolved to fastapi 0.136.1 / uvicorn 0.46.0 /
  pywebview 6.2.1.
- `.env.example` documents `PLAUDSYNC_UI_DEBUG` + `PLAUDSYNC_DEV_PORT`.
- `.gitignore` entry for `src/plaudsync/ui/static/` (Vite build output).

**Test results:** 128/128 pass (37 new UI tests across `test_ui_app.py`,
`test_ui_config_io.py`, `test_ui_state_reader.py`, `test_ui_sync_starter.py`,
`test_ui_runner.py`, `test_ui_auth_mask.py`, `test_main_ui_subcommand.py`;
+ 91 pre-existing). Bandit `-r src/plaudsync/ui/ -ll`: zero high/medium
issues, 2 expected low (subprocess.Popen with explicit list args, no shell=True).

**Smoke test (manual, in-process uvicorn):**

| Step | Result |
|---|---|
| `create_app(c:/tmp/plaudsync-smoke)` cold start | uvicorn ready in <500 ms on OS-assigned port |
| Lifespan auto-seed | `c:/tmp/plaudsync-smoke/config.yaml` written; `${STATE_ROOT}` substituted to actual path; YAML parses |
| `GET /api/healthz` | 200 + `{"status":"ok"}` + CSP header (`default-src 'self'`...) |
| `GET /api/state` | 200, `sync.status=idle`, `recordings=[]` |
| `GET /api/config` | 200, `parsed.projects` keys = `[ProjektAlfa, KlientBeta, Interní]`, `parse_error=null` |
| `PUT /api/config` (invalid path) | 422 with detail (JSON-shape errors visible in body) |
| Server shutdown via `should_exit=True` | clean exit, no zombie process |

**Implementation deviations (documented for review):**

- **CSP middleware mounted middle-of-handler-list, StaticFiles last.**
  Initially placed StaticFiles before /api/sync/start endpoint; moved
  to right before `return app` to avoid catch-all `/` mount intercepting
  /api/* routes.
- **`_open_ui_state` UI-local SQLite helper** added in `app.py` instead
  of reusing sync-core's `open_state` directly. Reason: FastAPI sync
  handlers run in a worker thread pool while lifespan runs in the
  asyncio thread; one connection has to be reusable across both, which
  requires `check_same_thread=False`. WAL mode + idempotent schema
  bootstrap preserved.
- **`block_network` marker** added at module level on `tests/test_ui_app.py`
  and `tests/test_ui_runner.py` (`allowed_hosts=["127.0.0.1", "localhost"]`)
  because TestClient and asyncio.run create localhost socketpairs that
  pytest-recording's `--block-network` gate otherwise intercepts. Marker
  syntax is `block_network(allowed_hosts=...)`, NOT `allow_hosts(...)`
  (corrected mid-implementation after first attempt failed).
- **`maybe_seed_default` is no-op even on empty file** (`target.exists()`
  is True for blank files). Test expectation matches: user content
  protection trumps re-seeding. Documented in module docstring.

**CD1-CD5 from plan all upheld:** auto-seed in lifespan only, no crash
on broken config (lazy validation), masked_token only on AuthVerifyResponse,
polling-only progress, single read-only conn in `app.state.db`.

**Open follow-ups (not blockers):**

- Sentry "2 pending events" stderr message after pytest run — likely
  `_configure_sentry()` capturing test artifacts. Not affecting tests;
  investigate during next observability sweep.
- `RecordingRow.plaud_folder` always `"_unknown"` in v0 (Dashboard spec
  Gap 2 acknowledged). v1 brainstorm to surface real folder names via
  separate `/folder/list/web` endpoint.
- `RecordingRow.classification_route` field for `_unmapped_<project>`
  badge variant (Dashboard spec Gap 1) — sync-core schema follow-up.

**Branch state:** `feat/ui-backend` ready for `/security-review` (new
HTTP surface + subprocess spawn + CSP middleware) before merge to main.
Frontend writing-plans cycle is the next blocker for full UI ship —
StaticFiles mount in `app.py` is conditional on `src/plaudsync/ui/static/index.html`
existence, which the frontend plan's Vite build pipeline produces.

---

## 2026-04-25 — UI frontend implementation plan written

`docs/superpowers/plans/2026-04-25-ui-frontend.md` published. 15 tasks
transcribing the validated Claude Design prototype (`frontend/PlaudSync UI.html`,
1222 LoC, 5 scenarios) into a Vite + React 19 + TS strict + Tailwind 4
project at `frontend/`. Production build copies dist to gitignored
`src/plaudsync/ui/static/` (umbrella E1/E3) for FastAPI StaticFiles mount.

### Key transcription decisions

- **No global store library** (umbrella D2): app-level toasts + banners
  via two minimal React Contexts (`ToastsProvider`, `BannersProvider`).
  Per-component dismiss state stays local with `useState`.
- **No test framework** in MVP (umbrella E6): verification = TS strict +
  manual smoke split into Phase 1 (mock-data, this branch) and Phase 2
  (live backend, after `feat/ui-backend` lands on master).
- **Dev mock layer gated by `import.meta.env.DEV`**: `dev/MockProvider`
  seeds TanStack Query cache with prototype `SCENARIOS` so the entire
  Dashboard + Settings flow is exercisable without a backend.
  `staleTime: Infinity` in dev keeps mock fresh; production tree-shakes
  the entire `dev/` directory via Vite dead-code elimination.
- **CSP-friendly bundle** (umbrella E5): `modulePreload.polyfill: false`
  in vite.config.ts removes the inline preload script; JetBrains Mono
  self-hosted via `@fontsource` so `connect-src 'self'` stays strict.
- **Bundle target ≤ 200 KB gzipped** (umbrella AC #4): `check-bundle-
  size.mjs` postbuild script warns over budget; W-U2 hard threshold 500
  KB. Realistic estimate: ~130 KB (React+ReactDOM 45 KB, query 14 KB,
  router 12 KB, app code ~50 KB).

### Settings spec v0.1 review fixes incorporated

- Gap 1 multi-error: `InlineConfigErrors.tsx` first-inline + `(+N
  dalších)` `<details>` expansion + click-to-promote.
- Gap 2 Option A: `AuthVerifyResponse.masked_token` (server-rendered
  first_8+15dots+last_4); ConnectionPanel implicit-verify on mount.
- Gap 3: `ConfigResponse.parse_error` surfaces inline + toast on mount.
- Gap 4: dirty-Reload triggers `window.confirm("Zahodit neuložené
  změny?")`.
- Gap 9: textarea `Tab → 2 spaces`, `Shift+Tab → dedent`, `Esc → blur`,
  hint footer "Tab pro odsazení • Esc pro opuštění editoru".

### Open follow-ups (post-merge, not blockers)

- Dashboard Gap 1 — `_unmapped_<project>` badge variant blocked on
  backend `RecordingRow.classification_route` field (sync-core spec
  follow-up; not added to current plan).
- Dashboard Gap 4 — log viewer modal: deferred to v1.1+. MVP behavior
  is a toast pointing user to `plaudsync.log` in project dir.
- Settings Gap 5 — YAML syntax highlight: deferred per spec.

Phase 2 smoke (live-backend ACs) gated on `feat/ui-backend` merge.

---

## 2026-04-25 — UI backend implementation plan written

`docs/superpowers/plans/2026-04-25-ui-backend.md` published. 19 TDD
tasks covering 6 new modules under `src/plaudsync/ui/` (`config_io.py`,
`state_reader.py`, `sync_starter.py`, `app.py`, `runner.py`, package
init) + `auth.mask_token()` helper + `__main__.py` `ui` subcommand with
`--dev` flag + 3 runtime deps (`fastapi`, `uvicorn`, `pywebview`).

### Key cross-spec decisions documented in plan

Plan resolves five overlaps/ambiguities between umbrella v0.2, Dashboard
v0, and Settings v0.1 specs (locked as CD1–CD5 in plan):

- **CD1:** DEFAULT_YAML auto-seed lives in UI lifespan (NOT sync-core
  CLI). Sync-core behavior unchanged (missing config = exit 7). UI
  substitutes `${STATE_ROOT}` literal to actual env-var path **at write
  time** so the seeded file passes sync-core absolute-path validation.
  This avoids needing to extend `config.load_config` with substitution
  logic — Settings spec D8 substitution rule is satisfied transparently
  for the seed path; future user-edited configs use real paths only.
- **CD2:** Lifespan does NOT crash on broken existing config — resolves
  overlap between umbrella spec ("fail-fast crash → ConnectionLostOverlay")
  and Settings spec Gap 3 ("GET /api/config returns broken YAML +
  parse_error so frontend shows inline error on mount"). Lifespan only
  validates STATE_ROOT presence + auto-seeds missing config. Validation
  is lazy in GET/PUT handlers; sync subprocess exit 7 surfaces as 500
  spawn_failed banner.
- **CD3:** `masked_token` lives only on `AuthVerifyResponse` (Settings
  spec Gap 2 Option A). `ConfigResponse` does NOT carry it. Backend
  computes mask via `auth.mask_token(token)` = first_8 + "•"×15 + last_4
  (≥ 12-char tokens) or "•"×20 fallback. `null` only on
  `PlaudTokenMissing`; populated even on `PlaudTokenExpired` since token
  shape is known.
- **CD4:** Polling-only progress (no SSE) — re-confirms umbrella B3.
- **CD5:** Single SQLite read-only conn lives in `app.state.db` over
  lifespan; WAL mode lets sync subprocess write concurrently.

### Frontend handoff

Frontend Vite project (React + TS + Tailwind + TanStack Query under
`frontend/`) is **out of scope** of this plan. Once UI backend lands on
master, separate writing-plans cycle produces frontend plan consuming
Dashboard + Settings screen specs. `StaticFiles` mount in `app.py`
(Task 15) is conditional on `src/plaudsync/ui/static/index.html`
existence — frontend plan owns the Vite build output drop into that
path. Pydantic models on `app.py` (`StateResponse`, `RecordingRow`,
`ConfigResponse`, `AuthVerifyResponse`, etc.) are the canonical wire
contract that frontend TS types must mirror.

### Branch + execution

Plan default execution: `superpowers:subagent-driven-development` (same
pattern that succeeded for sync-core plan). Branch: `feat/ui-backend`
from master. Each task = one fresh subagent + two-stage review.
Architecturally significant change (new HTTP surface + subprocess spawn
+ CSP) — `/security-review` mandatory before merge.

### Process notes

Independent self-review during plan writing surfaced one cross-spec
contradiction (CD2: umbrella "fail-fast crash" vs Settings "show inline
error"). Resolution favors the newer Settings spec because the umbrella
predates Settings v0.1 review fixes. This is the second consecutive
plan-writing session where independent review caught a real
contradiction (Settings spec v0 review caught Gap 2 C→A flip). Pattern
worth tracking: cross-spec ambiguities tend to surface only when a
third actor (plan, code, third spec) tries to consume both. Formalize
"cross-spec consistency check" as a writing-specs / writing-plans gate
when ≥ 2 specs share a contract surface.

---

## 2026-04-25 — Sync core smoke test PASS, branch merged + deleted

Manuální smoke proti reálné Plaud Cloud po merge `feat/sync-core` →
`master` (`9a6b6a5`):

| Krok | Výsledek |
|---|---|
| `python -m plaudsync verify` | exit 0, region probe + token OK (~3s) |
| 1. sync (~5 min) | exit 0, 92 nahrávek staženo |
| state.db | `sync_runs(1, exit=0, new=92, skipped=0, failed=0, manual)`; 92× status='downloaded' |
| 2. sync (idempotence) | exit 0, `new=0, skipped=0, failed=0` — since filter zastavil iterátor na page 1 |
| log audit | 4 INFO řádky, 0 výskytů `title`/`file_name`/`temp_url`/`Bearer` |

**Pozorování:**

- `plaud_folder` fallback fungoval — všech 92 nahrávek v `Unclassified/_unknown/`
  protože `from_raw` nedostal `filetag_id` ani `tag_ids[0]` z reálné API
  (DefaultBucketClassifier → unclassified branch). Future v1 brainstorm: rozhodnout
  jestli zůstat u `_unknown` nebo dotahovat tag display name přes endpoint
  `/folder/list/web`.
- České diakritiky v filename zachované (`_slugify` `[^\w\-]+` s `re.UNICODE`):
  `Schůzka_FHB_Příprava_…`, `Marek_Bartoš_Socio-etické_chování_LLM_…`.
- Pagination + since filter: druhý běh 0 API calls na listing po prvním page
  (since marker zastavil iterátor) — efektivní pro 1h Task Scheduler cadence.
- Throughput: 5 min / 92 nahrávek ≈ 3 sec/recording vč. temp-url + S3 stream.
  Single-threaded, bezpečné pro Task Scheduler interval ≥ 1h.

**State po smoke:** `feat/sync-core` lokální branch smazán (`git branch -d`).
Repo state: master HEAD `9a6b6a5` (merge commit), `C:/PlaudSync/` obsahuje
state.db + 92 .mp3 + plaudsync.log. Kill criteria L-1..L-18 nezapálené.

Další logický krok: Task Scheduler hookup — vytvořit periodic job pro
`python -m plaudsync` každou hodinu. Mimo sync-core scope.

---

## 2026-04-25 — Sync core code review: 3 hardening fixes + 2 deviation notes

Independent code-reviewer agent run proti `feat/sync-core` (HEAD `a8ab7d2`)
vrátil APPROVED_WITH_FIXES. Aplikováno v commitu `abf4a57`:

**Hardening (Important):**
- I-1: `_region_probe` allowlist `https://*.plaud.ai` — bez guardu by attacker
  schopný falšovat API odpověď přesměroval `_base_url` na vlastní host a token
  by tekl na další request.
- I-2: `download_audio` vynucuje `https://` na presigned URL + `allow_redirects=False`
  na S3 leg. Legitimní S3 presigned URL nikdy nepotřebují redirect.
- I-3: `_process_recording` unlinkuje partial file na jakoukoli mid-stream
  exception (předtím jen na size mismatch). Bránění UI/file watcheru zobrazit
  half-recording s real-looking name.

**Documented deviations (no fix):**
- I-9: `__main__.py:94-96` přidal `FileNotFoundError → exit 7` handler nad rámec
  spec. Důvod: `load_config` raisí FileNotFoundError když chybí config.yaml,
  ne ConfigValidationError. Beneficial deviation — uživatel dostane stejný
  exit 7 místo opaque exit 1. Ponechano.
- M-8: `sync.py:62-66` Sentry `recording_failed` capture vynechal
  `set_context("sync_run", {"run_id": ..., "trigger": ...})` per spec line 506-507.
  Trigger není v `run_sync` scope u failure pointu — vyžadovalo by threading.
  Defer do follow-up; má-li triage nedostatečnou kontext info, doplnit pak.

Cassette M-6: `test_sync_happy_path_*` body měl unscrubbed title
`"04-25 Test: meeting"` — přepsáno na `"<redacted-title>"`.

Branch po fixech: 79/79 testů zelených (5 nových testů pro hardening).

---

## 2026-04-25 — Sync core implementation plan written

`docs/superpowers/plans/2026-04-25-sync-core.md` published. 16 TDD
tasks covering 8 new modules + 4 modifications. Endpoint discovery
(5 community Plaud clients reverse-engineered) embedded as appendix
in spec.

Key decisions confirmed by discovery:
- `since` filter is **client-side** (Plaud has no server-side `since`);
  iterator stops early on first older record (desc by start_time).
- `plaud_folder` is a **UUID** (`filetag_id` / `tag_ids[0]`), not a
  display name. v0 ships UUIDs; v1 brainstorm resolves UUID → name.
- Audio download: temp-url JSON → S3 presigned URL (no auth header on
  S3). Two-step pattern.

Branch: `feat/sync-core` (created from master at start of Task 1).

---

## 2026-04-25 — Settings spec v0 → v0.1: review fixes applied

Independent code-reviewer agent run proti `2026-04-25-settings-screen-design.md` v0 (commit 340913a) vrátil 5 must-fix items + 8 minor nits. Vše opraveno v jednom revisi commitu.

**Must-fix:**

1. **Gap 2 flipped C → A.** v0 doporučovala "frontend constant 20 dots" (Option C), což je regression proti UI architecture umbrella line 841 (která depictuje real masked token `eyJ•••AbcD`). v0.1 specifies Option A: backend computes mask `first_8 + "•"×15 + last_4` server-side, returns v `AuthVerifyResponse.masked_token`. JWT header bytes nejsou PII, separation of concerns (config endpoint nesmí cross-couplovat auth state). Settings mount triggers implicit verify to populate.
2. **D8 DEFAULT_YAML seed paths rewritten** — v0 měl `D:\Recordings\...` placeholders co fail config validation na machine without `D:\`. v0.1 uses `${STATE_ROOT}\Recordings\...` per Gap 7 reasoning + dokumentuje literal `${STATE_ROOT}` substitution rule.
3. **Gap 1 promoted recommend → decided.** v0 mělo Gap 1 jako "recommend" ale AC #8 testovala jako decided spec. v0.1 spec decides definitive UX: first error inline + trailing button "(+N dalších chyb)" + click expands `<details>` list + click on item promotes to current (gutter highlight switches).
4. **Gap 9 added: textarea Tab key behavior.** Plain `<textarea>` Tab moves focus, breaking YAML indent edit. Decision: `onKeyDown` interceptor inserts 2 spaces (Shift+Tab dedents); Esc blurs textarea jako keyboard nav escape hatch. ~15 LoC.
5. **D11 added: privacy discipline note** per CLAUDE.md "never inline business labels in messages". Forbidden patterns + grep-able acceptance criterion (#19).

**Minor nits applied:**

- Gap 10 added: gutter perf with large configs (memoize line-number array; 500-line cap in Out of scope; aria-hidden on gutter).
- DEFAULT_YAML auto-seed promoted from Open question to **cross-spec impact item** — sync-core spec needs v0.3 revision (auto-seed in `config.load_config()` + `${STATE_ROOT}` substitution rule + parent mkdir for seed paths).
- LoC budget phrasing fixed ("90 % slack" → "~90 LoC headroom").
- AC expanded 16 → 20: auto-verify mount, multi-error promote-to-current, Tab indent, gutter perf, privacy grep.
- TS type fixed: `masked_token` removed from `ConfigResponse`, added to `AuthVerifyResponse`.

**Verdict:** review verdict was APPROVE WITH MINOR FIXES; v0.1 ships all must-fixes + relevant nits. No spec-blocking gaps remain.

**Process note:** code-reviewer agent surfaced exactly the kind of cross-spec contradictions writer's-eyes miss (v0 had `masked_token` v ConfigResponse TS type which contradicts both umbrella spec and the spec's own Gap 2 recommendation). Confirms value of independent review pass after spec writing — formalize jako step v writing-specs cycle pro umbrella+per-screen specs.

---

## 2026-04-25 — Settings screen spec: extracted from prototype + review delta

Companion k Dashboard specu (zápis níže). Stejný `frontend/PlaudSync UI.html` prototype obsahuje i Settings screen (ConnectionPanel + ConfigPanel + YamlEditor) — extracted contract proti UI architecture umbrella v0.2 + sync-core v0.2 (config.py + ConfigParseError) + auth design (PlaudTokenMissing/Expired).

Output: `docs/superpowers/specs/2026-04-25-settings-screen-design.md`. Sekce:

- **10 design decisions extracted** (D1–D10): layout (ConnectionPanel above ConfigPanel), token display contract (masked, "z .env" chip, hint blok), verify button state machine (idle/verifying/success/error 5 states), ConfigPanel header + Save/Reload + line counter, YamlEditor gutter+textarea+inline error footer (scroll-sync, 13/20px JetBrains Mono metrics, line highlight on error), Save button state machine, Reload behavior, DEFAULT_YAML seed template, banner derivation v Settings (token-expired surface), full localization string lock contract.
- **Component tree** s LoC budget odhadem (~300 LoC pro Settings subset; combined Dashboard + Settings ~910 — within 500–1000 budget, 90% slack).
- **TS types mirror Pydantic + auth** (ConfigResponse, ConfigSaveResponse union, ConfigSaveErrors, AuthVerifyResponse, ConfigParseError).
- **Public hooks** signatures (useConfig, useSaveConfig, useVerifyAuth) s TanStack Query 422-handling note (PUT /api/config 422 throws via fetch wrapper, vs auth verify 200+ok=false structural-result pattern).
- **8 gaps** (review delta) — 3 s decision, 5 deferred do implementation cyklu:
  - Gap 1: Multi-error 422 — prototype shows only first; recommend first inline + "(+N dalších)" hint with click-to-expand modal.
  - Gap 2: Token masking — frontend hardcoded vs backend-rendered? Recommend Option C (frontend constant 20 dots + "z .env" chip; no PII surfaced).
  - Gap 3: Inline parse error from GET /api/config (existing broken config on mount) — UI must immediately surface; mount effect.
  - Gap 4: Reload silently discards local edits (recommend native `confirm()` if dirty).
  - Gap 5: Plain textarea, no syntax highlight / auto-indent / bracket pair (skip for MVP, ~30–80 KB cost not worth).
  - Gap 6: Save always-enabled, no dirty detection (acceptable v0).
  - Gap 7: DEFAULT_YAML seed — sync-core auto-creates vs user manual? Cross-spec note for sync-core impl: auto-create v config.load_config + relax parent-must-exist for seed.
  - Gap 8: PUT /api/config 422 vs auth verify 200+ok=false convention split — document v client.ts wrapper.

**Open questions (for implementation cycle):** masked_token placement (verify response / config response / frontend constant — default C), multi-error display (first-only with hint vs all-listed), reload confirm dialog UX (native vs custom modal vs silent), DEFAULT_YAML seed location (sync-core vs UI backend — cross-spec impl decision), save dirty disable (always-enabled vs disabled-when-clean).

**Implementation gating:** Settings frontend writing-plans čeká na sync-core impl (Config + ConfigParseError) + UI backend impl (ConfigResponse shape) + Dashboard spec (companion, already shipped at 49c8e4e). Sequence unchanged: sync-core impl (in progress, 7cd5885 latest) → UI backend plan → UI backend impl → Frontend plan (Dashboard + Settings combined) → Frontend impl.

**Process note:** stejný extracted-from-prototype workflow jako Dashboard. User design je hotový v prototype; spec je contract + review findings + acceptance criteria, ne re-design. Brainstorming skill záměrně neinvokován (žádné design rozhodnutí k prozkoumání).

---

## 2026-04-25 — Dashboard screen spec: extracted from prototype + review delta

User měl Dashboard design hotový v Claude Design prototype (`frontend/PlaudSync UI.html`, commit 1ea6bd3 — 1222 LoC HTML+React+Tailwind, 5 plně funkčních scenarios + ConnectionLostOverlay + 12 sample recordings). Místo brainstormu od nuly proběhl **review** prototype proti UI architecture umbrella v0.2 + sync-core v0.2 specs.

Output: `docs/superpowers/specs/2026-04-25-dashboard-screen-design.md`. Sekce:

- **10 design decisions extracted** (D1–D10): layout, SyncNowPanel 6 states, RecordingsList row format, ProjectBadge color taxonomy, SyncStatusBadge 5 states, BannerStack derivation rules, Toast triggers, ConnectionLostOverlay terminal error UX, live recordings list during sync, polling cadence (5s idle / 1.5s running).
- **Component tree** s LoC budget odhadem (~610 LoC pro Dashboard subset, total frontend ~810 — within UI umbrella 500-1000 budget).
- **TS types mirror Pydantic** (StateResponse, RecordingRow, SyncState, SyncProgress, ClassificationStatus, RecordingStatus).
- **Public hooks** signatures (useStateQuery, useStartSync) s TanStack Query polling pattern.
- **7 gaps** (review delta) — 3 s decision, 4 deferred do implementation cyklu:
  - Gap 1: `_unmapped_<project>` not visually distinct → add 3rd badge variant nebo `classification_route` field (open).
  - Gap 2: `plaud_folder` is UUID v0 (sync-core spec confirms), prototype mock shows readable strings (real production data won't match).
  - Gap 3: `target_dir` not displayed (acceptable v0; tooltip on ProjectBadge as Phase 2).
  - Gap 4: "Zobrazit log" action behavior undefined (4 options A/B/C/D, default C = toast pointing to file).
  - Gap 5: Loading state during cold start (skeleton vs spinner — pick during impl).
  - Gap 6: Live recordings no animation (acceptable v0).
  - Gap 7: Banner dismissal across sessions (acceptable v0; localStorage-backed if feedback needs).

**Open questions (for implementation cycle):** classification_route field design, log action behavior, loading skeleton vs spinner, UUID truncation in plaud_folder display.

**Implementation gating:** Dashboard frontend writing-plans čeká na sync-core impl (Pydantic shapes) + Settings spec + UI backend writing-plans + impl. Sequence: sync-core impl → Settings review → UI backend plan → UI backend impl → Frontend plan (Dashboard + Settings combined) → Frontend impl.

---

## 2026-04-25 — Categorization implementation: regex-only classifier shipped

Implementation execution of `docs/superpowers/plans/2026-04-25-categorization.md` via subagent-driven-development. 9 commits on master (Tasks 1–9).

### What landed

- **New module:** `src/plaudsync/categorization.py` (~75 LoC) — frozen `ClassificationResult` dataclass (`status`, `project`, `matched_date`) + `classify(title, created_at)` function. Handles `(YYYY-)?MM-DD <Project>: <rest>` title format. Emits structured log warnings for year-mismatch and invalid-date cases (never inline business labels in message text).
- **Tests:** 14 unit tests in `tests/test_categorization.py` + 1 scrubber test in `tests/test_smoke.py` (plaud_folder redaction).
- **Observability:** `observability._REDACTED_KEYS` extended with `plaud_folder` key (defense in depth, kill #18 — ensures plaud_folder UUID never surfaces in Sentry even if sync engine logs it).
- **Repo cleanup:** `anthropic`, `msal`, `deepeval` removed from deps; `tests/evals/` directory removed; DeepEval / golden-set references purged from CLAUDE.md + settings.json.
- **Kill criterion swap:** #5 updated from "LLM accuracy ≥ 70 %" to "regex coverage rate ≥ 90 % over sliding 30-day window" (SPEC.md already at v0.2, sync-debug + cassette-refresh skills updated).
- **Doc cascade (Task 9):** SPEC.md confirmed v0.2 (no edits needed). CLAUDE.md, DEV_LOG.md, pyproject.toml, settings.json, sync-debug SKILL.md, cassette-refresh SKILL.md, memory/project_plaud_categorization.md all updated.

### Reference plan

`docs/superpowers/plans/2026-04-25-categorization.md`

---

## 2026-04-25 — Categorization + sync-core implementation plans written

Two writing-plans outputs published:

- `docs/superpowers/plans/2026-04-25-categorization.md` — 9 TDD tasks for single-layer regex classifier (~50–70 LoC src + ~150 LoC tests). Includes repo-wide cleanup (drop `anthropic`/`msal`/`deepeval`, remove `tests/evals/`, swap kill criterion #5 from LLM accuracy to regex coverage rate).
- `docs/superpowers/plans/2026-04-25-sync-core.md` — 16 TDD tasks for sync core (8 new modules + 4 modifications). Pre-baked endpoint discovery appendix in sync-core spec (5 community Plaud clients reverse-engineered by Explore subagent).

### Endpoint discovery (sync-core spec appendix)

Reverse-engineered from `sergivalverde/plaud-toolkit`, `leonardsellem/plaud-sync-for-obsidian`, `iiAtlas/plaud-recording-downloader`, `arbuzmell/plaud-api`, `openplaud/openplaud`. Cross-validated High-confidence endpoints:

- `GET /file/simple/web?skip=N&limit=50&is_trash=0` — listing + region probe (offset pagination).
- `GET /file/temp-url/{id}` → JSON with `temp_url` (S3 presigned, no auth header on S3).

Two material spec corrections from discovery:

1. **`since` is client-side only** — Plaud listing has no server-side `since` param. Iterator stops early on first older record (Plaud returns desc by `start_time`).
2. **`plaud_folder` is a UUID** (`filetag_id` / `tag_ids[0]`), not a display name. v0 ships UUIDs through path_resolver sanitization; v1 brainstorm resolves UUID → name via separate (un-discovered) `/tag/list` endpoint.

### Plan execution order recommendation

1. **Categorization plan** first (smaller, no external dependencies, repo cleanup unblocks subsequent work).
2. **Sync-core plan** second (depends on categorization `ClassificationResult` + auth layer + portalocker).
3. **UI plan** third (after Claude Design prototype + per-screen brainstorm cycles).

Both plans use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` for execution.

---

## 2026-04-25 — Cascade: per-project absolute paths

User požadavek: každý projekt má vlastní lokální cílovou cestu, žádný společný kořen (např. ProjektAlfa na `C:\`, ProjektBeta na `D:\`). Tento požadavek vyšel najevo po obdržení Claude Design ZIP prototypu — Settings YAML editor potřeboval konkrétní schema.

### Q&A z brainstorm session

| # | Otázka | Volba | Důvod |
|---|---|---|---|
| 1 | Kde žije `state.db` + lock file (když není společný recordings root)? | **A** Nový env var `PLAUDSYNC_STATE_ROOT` (state-only umístění, žádné recordings) | Vyhne se duplicitě YAML+env. Bootstrap location musí být env var, behavioral routing je YAML. |
| 2 | Jak řešit "title matchne projekt, config ho nezná"? | **A** Soft fallback do `${unclassified_dir}/_unmapped_<project>/` | Symetrie s "title nematchne". Sync pokračuje, log warning + sentry tag. User vidí přesný project label v Exploreru. |
| 3 | Per-Plaud-folder subdivize unclassified bucketu? | **A** Zachovat | Beze změny chování v původním v0.1. Kontext z Plaud workflow se neztrácí. |

### YAML schema

```yaml
unclassified_dir: D:\Recordings\Unclassified
projects:
  ProjektAlfa: C:\Projects\Alpha\Recordings
  ProjektBeta: D:\Clients\Beta\Audio
```

Validace v `config.py.load_config()`: `unclassified_dir` + všechny project paths absolutní, parent existuje, žádné `..` (path traversal guard).

### Cascade dopady (4 commits)

1. **categorization v0.2** (025e609) — `ClassificationResult.target_subdir` dropped, `classify()` ztrácí `plaud_folder` parametr, `_sanitize_folder_name` přesunut. Test count 12 → 10.
2. **sync-core v0.2** (a1eac75) — nové moduly `config.py` + `path_resolver.py`. Env var rename. `recordings.local_path` absolutní. Nový exit code 7 (ConfigValidationError). Test count 24 → 37.
3. **ui-architecture v0.2** (aa0238e) — env var rename, lifespan handler načítá config.yaml + state.db z STATE_ROOT, `RecordingRow.target_subdir` → `target_dir` (absolutní). Settings empty-config template ukazuje konkrétní YAML schema.
4. **SPEC.md v0.2 + .env.example** (this commit) — single-layer regex deklarace, M365+Anthropic z paid deps pryč, success criterion #2 změněno z "LLM accuracy" na "regex coverage".

### Architectural insight

YAML config = **per-project routing** (kde co skončí). Env var = **bootstrap** (kde najít YAML). Po cascade je separation čistá, žádná chicken-and-egg.

### Process notes

- Brainstorming skill aplikován (continued v stejné conversation jako UI architecture brainstorm). 3 clarifying questions (Q1/Q2/Q3) s explicit recommendations a counterarguments. User schválil `OK` → proceeded with cascade in 4 separate commits per spec (jeden commit per spec = lepší git log než mega-commit).
- Counterargument bias watch (z 2026-04-24 SPEC pivot): user opět zvolil 3× recommendation. Watch item formalizace stále `#1` z workflow memory (> 2 korekce per task = trigger; opak = under-watch).
- Discovered v0.2 trigger: user feedback z prototypu odhalil missing config schema detail. **Lekce:** spec brainstorm bez mockupu může minout konkrétní data shapes, které prototyp explicitně potřebuje. Pro budoucí umbrella specy zvážit "data shape draft" pass před writing.

---

## 2026-04-24 — Auth layer implemented (plan 2026-04-24)

Plán `docs/superpowers/plans/2026-04-24-plaud-auth.md` dokončen. 12 testů zelených (`pytest tests/`), bandit clean (61 LoC auth modulů), log a Sentry scrub hygiene gates prošly (smoke token `unique-smoke-token-xyzzy-9876` neunikl).

### Odchylky od plánu (zaznamenané rozhodnutí během implementace)

- **Task 1 přeskočen.** Plán počítal s hand-crafted VCR cassettami. User v novém zadání vyžádal `@pytest.mark.vcr` **s reálnou Plaud API call** — cassetty jsou nyní recorded proti skutečnému API (scrubnuté authorization + Set-Cookie).
- **Verify endpoint změněn z `/me` na `/file/simple/web`.** Plaud nemá dedikovaný auth-check endpoint (ověřeno v `arbuzmell/plaud-api` zdroji: `session.py` jen reactive-auth, žádný verify call). `/me` vrátil 404. Použili jsme `FILE_SIMPLE = "https://api.plaud.ai/file/simple/web"` — nejlehčí file-listing endpoint, který je authenticated.
- **VCR conftest upgrade.** Přidán `VCR_RECORD_MODE` env var pro one-off re-recording bez trvalého loosening `conftest.py` (default zůstává `"none"` = replay-only).
- **Sentry SDK 2.x API.** Původní plán používal `sentry_sdk.Hub.current.client` a `push_scope()` — oba deprecated. Implementace používá `is_initialized()` a `new_scope()`.
- **Test exit-code regressions.** Testy volající `main()` musí monkeypatchnout `sys.argv` (kvůli argparse) i `load_dotenv` (kvůli vyplněnému `.env`).

### Region mismatch — tech debt pro sync-engine

Plaud API na `api.plaud.ai/file/simple/web` vrátil HTTP 200 **s body** `{"status":-302,"msg":"user region mismatch","data":{"domains":{"api":"https://api-euc1.plaud.ai"}}}`. Účet je EU region → měl by používat `api-euc1.plaud.ai`. Auth verify stačí HTTP 200 (token valid), ale **sync-engine feature MUSÍ parsovat region redirect** a používat regional endpoint pro listing/download recordings. Zaznamenáno jako sync-engine prerequisite.

### Co je hotové

- `src/plaudsync/auth.py` — `load_token()` + `PlaudTokenMissing` + `PlaudTokenExpired`
- `src/plaudsync/plaud_client.py` — `PlaudClient(token)` + `verify()` + context manager
- `src/plaudsync/__main__.py` — argparse s `verify` subcommand, exit codes 2/3, `_capture_sentry()` helper s fingerprint+tag
- `src/plaudsync/observability.py` — extended `_scrub_string` s Bearer + PLAUD_API_TOKEN value redaction
- 10 auth testů (4 `test_auth.py`, 2 `test_plaud_client.py` vč. scrubbed cassetty, 4 `test_main_exit_codes.py`)
- `tests/conftest.py` — VCR_RECORD_MODE env var support

### Další krok

Viz user rozhodnutí — Claude Design UI prototyp → per-screen brainstorm, nebo sync-engine brainstorm (musí zahrnout region redirect handling).

### Process notes

- TDD cyklus držel disciplínu: failing-test commit **samostatně** od impl commitu, každý TDD cycle jeden red → green pár.
- Subagent dispatch (Task 1 scaffolding) byl zrušen userem a implementováno přímo — odlišný dynamikou proti skill flow, ale výsledek funguje.
- Branch `feat/plaud-auth` obsahuje ~14 commitů (plán adjust, 2 commity per task ~ 8 tasks, post-flight TBD). Před mergem do master: `/security-review` + manual review diff.

---

## 2026-04-24 — SPEC pivot: UI z out-of-scope do core scope

Paralelně s auth brainstormem vyšlo najevo, že user má širší představu o produktu, než zachycoval v0 draft. SPEC.md explicitně říkal "UI / web dashboard = out of scope". Pivot tento řádek smazal a přidal UI vrstvu do core v0.

### Brainstorm session — kontext metodiky

Brainstorm byl veden podle [Superpowers `brainstorming` skill SKILL.md](../../Users/ai_martint/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/brainstorming/SKILL.md). V té konkrétní session, kde pivot proběhl, byl Skill tool call `superpowers:brainstorming` ještě odmítnutý s "Unknown skill" (session začala před `Developer: Reload Window`, viz samostatný záznam o verifikaci níže). **Fallback:** SKILL.md byl přečten přes `Read` tool a postupováno ručně podle něj (explore → clarifying → options → present → write spec → self-review). Po Reload Window by měl skill fungovat normálně — budoucí session už může volat `Skill("superpowers:brainstorming", ...)` přímo.

### Rozhodnutí z pivotu

| # | Otázka | Volba | Důvod |
|---|---|---|---|
| 1 | MVP scope | **A** Minimalistic (Dashboard + Sync Now + Settings, bez heat mapy) | Rychlejší feedback loop, UI reálně použitelné dřív než guess work pro advanced features. Heat mapa → v1.1 po 2 týdnech reálných dat. |
| 2 | Architektura | **C** GUI + CLI (SQLite + YAML = shared state) | Zachovává existing CLI invest, žádný daemon, žádný single point of failure, kill-criterion-friendly. |
| 3 | UI stack | **B** FastAPI + React + PyWebView | Claude Design prototyp (= React) přímo použitelný, desktop UX vs browser UX, Win11 WebView2 native. |
| 4 | UI lifecycle | **A** On-demand only | Menší scope pro MVP, žádný tray icon / autostart komplikace, clean separation (Task Scheduler = time-based, UI = user-triggered). |

### Dopady

- **`SPEC.md` updated** (v0 → v0.1): nová UI scope sekce, constraints (Node 20+, WebView2, sync idempotence), success criteria (UI cold start ≤ 3 s, Sync Now latence ≤ 2 s), architectural decisions (UI architektura rozepsaná), kill criteria (preambule k UI watch).
- **Auth spec zapsán** do `docs/superpowers/specs/2026-04-24-plaud-auth-design.md` — kompletní design vč. UI API consumer use case (FastAPI endpoint `POST /api/auth/verify`).
- **Následné brainstorm cykly:** každý UI subsystém dostane vlastní spec (Settings screen, Dashboard screen, Sync Now orchestrace, backend endpoints). SPEC.md je jen rámec.
- **LoC budget upgrade:** Python 1500–3000 (beze změny) + React/TS 500–1000 (nově).

### UI layer watch (kandidáti na budoucí kill criteria)

Tyto "watch items" nejsou formální kill criteria (zatím). Pokud některý začne triggerovat opakovaně, formalizujeme ho a přidáme do trackeru níže:

- **W-U1: WebView2 kompatibilita** — PyWebView na Win11 out-of-box spolehlivě? Pokud dev stanice ukáže crash rate > 1× týdně, re-evaluate (browser fallback).
- **W-U2: React bundle size** — MVP A (2 screens) by měl vejít pod 500 KB gzipped. Nad 1 MB = signal scope creep nebo špatně rozdělený import.
- **W-U3: Vite/Node dep churn** — npm ecosystem známý velkým dependency fan-outem. Pokud `npm audit` > 5 high-severity nevyřešitelných v průběhu 2 týdnů = re-evaluate frontend stack.
- **W-U4: Frontend build čas** — cold Vite build > 30 s = investigate / kill criterion kandidát (spolu s existing T-8 CI slowdown).
- **W-U5: Sync Now subprocess protocol** — progress streaming přes subprocess stdout je křehké na encoding / flushing. Pokud víc než 2 bugy v 1 měsíci, zvážit SQLite-based progress table místo stdout.

### User actions z brainstormu

- Připravit **prototyp v Claude Design** (2 screens: Settings, Dashboard) — předá jako podklad pro per-screen brainstorm.
- Až bude prototyp, otevřít per-feature brainstorm cykly (postupně, ne naráz).
- Ideation session pro "další užitečné nápady" — parkoviště nápadů po tom, co uvidíme prototyp.

### Process note (counterarguments bias watch)

Brainstorm šel striktně dle skill checklistu. User volil ze 4 options 4× recommendation — žádný pushback na zvolenou variantu. Co to může znamenat:
- (a) recommendations byly solidní a user je skutečně přijal;
- (b) formulace recommendations byla příliš persuasive a user neměl reálnou volbu;
- (c) user vím, kam chce, takže se jen ujistil, že můj návrh tam vede.

**Akce pro příští brainstorm sessions:** zvýšit důraz na **counterarguments** u vlastní recommendation (explicitně pojmenovat, kdy by uživatel měl zvolit jinou variantu). Watch: pokud i další brainstorm session skončí 100% alignment, formalizovat jako workflow bias (kill criterion #1 z memory: > 2 korekce per task = trigger; opak problému — žádná korekce = je to dobře nebo je to špatně?).

---

## 2026-04-24 — Hook smoke test: H-10 baseline measured

`.claude/hooks/pytest_on_edit.py` ověřen empiricky:

- **Manuální pytest baseline:** `pytest tests/ -x --lf -q` = 0.02 s test runtime, 3.9 s total wall clock (Python interpreter cold start + venv + pytest collection).
- **Hook simulation** (`echo '{"tool_input":{"file_path":"tests/test_smoke.py"}}' | python .claude/hooks/pytest_on_edit.py`) → exit 0, pytest 2 passed.
- **Hook automatický trigger po Claude Edit/Write**: empiricky neověřeno (Claude Code suppresí hook stdout/stderr v conversational view). Hook script sám funguje, takže pokud Claude Code hooks nefungují, je to platform issue, ne náš bug.

Kill criterion **H-10** (hook > 10 s @ 2 týdny → disable hook): aktuální 3.9 s wall = **39 % budgetu**. Pohoda. Threshold se může zhoršit, až přibude víc testů (zvlášť VCR cassette replay nebo DeepEval), monitorovat.

**Vytvořeno:** `tests/test_smoke.py` (2 trivial testy, jen aby pytest měl co collectovat — bez nich `pytest --lf` failuje s "no last failed" warningem v některých edge cases).

## 2026-04-24 — Sentry smoke test: L-18 partial leak + fix

První běh `scripts/sentry_smoke.py` proti Sentry produkčnímu DSN (free tier). PLAUDSYNC-1 event přišel, scrubbing částečně leakoval. Opraveno hned, druhý běh pending verifikace v UI.

### Findings (první běh)

| Co testováno | Status | Detail |
|---|---|---|
| `<path>` substituce v message | ✅ | `C:\PlaudRecordings\...mp3` → `<path>` |
| Tag `category` | ✅ | `<redacted-label>` |
| Tag `project_name` | ✅ | `<redacted-label>` |
| Context "recording" header | ✅ | `<redacted-label>` |
| **Inline `key=value` v message** | ❌ | `project=AcmeCorp-Internal`, `category=ProjectAlpha` prosvistly |
| **Tag `server_name`** | ❌ | `TOMISM` (hostname) prosvistlo |
| User Geography (IP-derived) | ⚠️ | `Ostrava, Czechia` — vyžaduje server-side "Prevent Storing of IP Addresses" v Sentry settings |

### Fixes (commit pending)

1. **observability.py** — přidán `_INLINE_LABEL_RE` pattern, který scrubuje `(category|project_name|...)\s*[=:]\s*<value>` v plain text stringech (exception messages, log lines).
2. **__main__.py** — `sentry_sdk.init(server_name="<redacted>", ...)` natvrdo přepíše hostname.
3. **CLAUDE.md** — nová sekce "Privacy / observability rules": **"Never inline business labels in exception messages or log strings."** Vždy přes `set_tag` / `set_context` / `logger.bind`. Důvod: scrubber regex je best-effort pro free-form text, easy miss.

### Architectural insight

Smoke test ukázal jemnou architekturní propast: **scrubber je defense-in-depth, ne primární obrana**. Primární obrana je **convention** — ne dávat business labels do free-form messages vůbec. Convention je v CLAUDE.md, scrubber je safety net pro slip-ups. Server-side Sentry rules (Sensitive Fields, IP scrubbing) jsou třetí vrstva.

### User action — completed

- ✅ Ověřeno v Sentry UI 23:25: druhý event (timestamp 23:23:45) má `project=<redacted-label>`, `category=<redacted-label>`, `server_name=<redacted>`. Message, tags i contexts všechny scrubnuté.
- ✅ Sentry Settings → "Prevent Storing of IP Addresses" zapnuto. Geography leak skončí u příštích eventů.
- ⏳ Resolve PLAUDSYNC-2 v Sentry UI (UnicodeEncodeError, můj bug v print, opraveno) — kosmetické, ne blokující.

**L-18 verified clean.** Privacy posture pro recording-processing tool ready pro produkční nasazení.

## 2026-04-24 — Superpowers verified (post Reload Window)

Po `Developer: Reload Window` ve VSCode a fresh chat session jsou Superpowers skills správně exponovány přes Skill tool. `/context` ukazuje:

**Skills přidané pluginem (17):** `using-superpowers` (meta), `brainstorming`, `test-driven-development`, `systematic-debugging`, `subagent-driven-development`, `verification-before-completion`, `requesting-code-review`, `receiving-code-review`, `dispatching-parallel-agents`, `executing-plans`, `writing-plans`, `writing-skills`, `using-git-worktrees`, `finishing-a-development-branch`, `superpowers:brainstorm`, `superpowers:write-plan`, `superpowers:execute-plan`.

**Custom agent přidaný pluginem:** `superpowers:code-reviewer` (353 tokens) — explicit subagent pro code review.

### Final baseline numbers

| Kategorie | Tokens | Změna proti pre-Superpowers |
|-----------|-------|------------------------------|
| Skills | 1.8k | +700 (z 1.1k) |
| Custom Agents | 353 | +353 (nová sekce) |
| System prompt | 9.4k | beze změny |
| **Project + plugin overhead celkem** | **~3.0k** | **+1.1k** |

**Superpowers footprint je extrémně levný — ~1.1k tokens nad pre-install baseline.** Hluboko pod jakýmkoli rozumným kill criterion threshold. Hard enforcement TDD (auto-delete code-before-test) by mělo být aktivní.

### Sekundární observace (od user)

User upozornil na potenciální dual-user issue: directory `c:/GitHub/PlaudSync` je vlastněna Windows uživatelem `martint`, zatímco Claude Code proces běží pod `ai_martint`. Vyřešeno přes `git config --global --add safe.directory C:/GitHub/PlaudSync`. Zatím **žádné funkční selhání**, ale risk indicator pro budoucí permission edge cases (antivirus, Windows Defender, file lock kdyby martint user otevřel stejný file současně).

**Aktualizace ze Sentry smoke testu (2026-04-24 ~23:13):** Při běhu `scripts/sentry_smoke.py` traceback ukázal cestu `C:\Users\martint\AppData\Local\Programs\Python\Python312\Lib\encodings\cp1250.py`. To znamená, že **Python 3.12 interpreter v `.venv/` (a ten, ze kterého byl venv vytvořen) je instalován pod uživatelem `martint`, ne `ai_martint`**. Důsledky:

- Per-user Python instalace (`%LOCALAPPDATA%\Programs\Python`) jiného uživatele je *čitelná* z `ai_martint` procesu (proto venv funguje), ale není *vlastněná* — Windows Defender / antivirus může intermittently blokovat.
- Kdyby `martint` reinstaloval / odinstaloval Python 3.12, venv v PlaudSync by se rozbil.
- Pokud bude potřeba upgrade Python (3.13+), instalace musí proběhnout pod správným uživatelem (ideálně `ai_martint` for full ownership, nebo system-wide install).

**Mitigace pro teď:** žádná akce, jen poznamenat. Pokud se objeví venv permission errors při příští `pip install`, tohle je primární podezřelý.

## 2026-04-24 — Baseline /context measurement (post Superpowers install) [SUPERSEDED]

> **Tento záznam byl nahrazen verifikací výše po Reload Window. Ponecháno pro historii rozhodnutí.**



`/context` po (údajné) instalaci Superpowers. Celkový context 279.3k / 1M (28 %), z toho 245.7k jsou aktuální messages (nezapočítávají se do harness baseline).

**Harness-only baseline** (vše kromě Messages + Autocompact buffer):

| Kategorie | Tokens |
|-----------|--------|
| System prompt (Claude Code + CLAUDE.md + auto-memory) | 9.4k |
| System tools (Read/Write/Edit/Bash/…) | 20.8k |
| System tools (deferred) | 15.1k |
| MCP tools (deferred) | 5.0k |
| Memory files (MEMORY.md + CLAUDE.md) | 2.3k |
| Skills (všechny Claude Code + User + Project) | 1.1k |
| **CELKEM** | **~53.7k** |

**Project-specific přírůstek** (to, co přidává PlaudSync harness):
- `CLAUDE.md` v project root: 1.8k
- `cassette-refresh` skill: 58 tokens
- `sync-debug` skill: 54 tokens
- **Celkem cca 1.9k tokens** — velmi štíhlé.

### ⚠️ Pozorování: Superpowers skills nevidím v context outputu

V `Skills` sekci výstupu jsou: `update-config`, `keybindings-help`, `simplify`, `fewer-permission-prompts`, `loop`, `schedule`, `claude-api`, `cassette-refresh`, `sync-debug`, `pruzkum`, `therapy`, `init`, `review`, `security-review`. **Žádná z typických Superpowers skills** (`brainstorming`, `test-driven-development`, `debugging-methodology`, `subagent-driven-development`, `creating-skills`) v listu není.

Možná vysvětlení:
1. Superpowers injektuje do **system promptu** (~9.4k) přes SessionStart hook, ne přes skills registry. Pak by footprint byl v system prompt číslu a my bychom to nepoznali z rozkladu. (Dle kola 2 průzkumu: *"The hook reads the using-superpowers meta-skill and injects it into Claude's system prompt wrapped in EXTREMELY_IMPORTANT tags."*)
2. Instalace proběhla, ale v této session se neprojevuje (potřeba restart / fresh session).
3. Plugin je instalovaný, ale skills se rozbalují on-demand a /context je ukazuje až po prvním použití.

**Akce k ověření:** v následující session napsat "použij Superpowers brainstorming skill pro nějaký malý brainstorm" — pokud skill odpoví, je aktivní. Pokud ne, přeinstalovat / zkontrolovat `/plugins` UI.

### Kill criterion H-9 — recalibrace

Original threshold ("context baseline > 15k tokens na session start") **byl špatně kalibrovaný** — neuvažoval s base Claude Code infrastrukturou (~55k tokens i bez jakéhokoli pluginu). Rekalibrace:

- **Claude Code infrastructure baseline** (bez projectu): ~50–55k — mimo kontrolu.
- **Project overhead budget** (to, co přidává PlaudSync harness + Superpowers inject do system promptu): **budget < 10k**, trigger > 15k.
- **Aktuální stav bez Superpowers**: project overhead ~1.9k (CLAUDE.md + 2 skills). Pokud Superpowers přidá do system prompt +5k, dostaneme se k ~7k — stále pod budget.

Revised kill criterion: **project overhead (nad Claude Code baseline 55k) > 15k** @ 1 měsíc → redukovat.

### 2026-04-24 — Harness bootstrap

Založena struktura projektu po průzkumech kol 1–4. Soubory vytvořeny: `SPEC.md`, `CLAUDE.md`, `DEV_LOG.md`, `.gitignore`, `.env.example`, `pyproject.toml`, `.claude/settings.json` + `.claude/hooks/pytest_on_edit.py`, `.claude/skills/{cassette-refresh,sync-debug}/SKILL.md`, `src/plaudsync/{__init__,__main__,observability}.py`, `tests/{__init__,conftest}.py` + `tests/evals/golden_set.yaml` skeleton.

Čeká na user actions: `pip install -e .[dev]`, Sentry account signup, `/plugin install superpowers`, baseline `/context` measurement, Windows Task Scheduler dry-run.

---

## Kill criteria tracker

18 pre-registered kill criteria z kol 1–4. Sleduj trigger risk měsíčně; při triggeru doplň záznam a rozhodnutí (follow/redesign/defer).

### Kolo 1 (workflow metodika)

| # | Criterion | Last check | Status |
|---|-----------|-----------|--------|
| 1 | > 2 korekce per task na 3+ tascích @ 2 týdny | — | not started |
| 2 | > 30 % false-pass v TDD (mock pass, real fail) @ 1 měsíc | — | not started |
| 3 | SPEC.md bez git update @ 4 týdny | 2026-04-24 (created) | active |
| 4 | Plan Mode overhead > 30 % @ 1 měsíc | — | not started |
| 5 | Regex match coverage < 90 % na sliding 30-day window | — | not started (swapped 2026-04-25 from LLM accuracy → regex coverage per categorization v0.2) |

### Kolo 2 (tooling)

| # | Criterion | Last check | Status |
|---|-----------|-----------|--------|
| T-5 | Cassette re-record > 1×/měsíc kvůli nestabilitě | — | not started |
| T-6 | DeepEval dependency conflict s Anthropic/OpenAI SDK | — | superseded 2026-04-25 (DeepEval dropped with regex-only categorization) |
| T-7 | Superpowers context pollution > 30 % nevyužíván @ 3 týdny | — | not started (pending install) |
| T-8 | CI slowdown > 30 s vs baseline @ 1 měsíc | — | not started |

### Kolo 3 (harness)

| # | Criterion | Last check | Status |
|---|-----------|-----------|--------|
| H-9 | **Project overhead > 15k tokens** nad Claude Code ~55k baseline @ 1 měsíc (recalibrated 2026-04-24) | 2026-04-24 | OK (~3.0k project+Superpowers overhead, 20% budgetu) |
| H-10 | PostToolUse hook > 10 s průměrně @ 2 týdny | 2026-04-24 | OK (baseline 3.9 s = 39 % budgetu, hook script funguje) |
| H-11 | Superpowers TDD enforcement selhává (> 20 % commitů má testy po source) | — | not started |
| H-12 | Harness blokuje cross-platform práci | — | not started |
| H-13 | Task Scheduler miss rate > 5 %/měsíc OR sync potřeba mimo laptop uptime | — | not started |

### Kolo 4 (lifecycle)

| # | Criterion | Last check | Status |
|---|-----------|-----------|--------|
| L-14 | Sentry free tier překročen > 2× @ 3 měsíce | — | not started |
| L-15 | /review > 80 % false positives @ 2 týdny | — | not started |
| L-16 | Architecture drift — za 3 měsíce nerozumím SPEC.md | — | not started |
| L-17 | Writer/Reviewer > 2× čas vs plain Plan Mode @ 1 měsíc | — | not started |
| L-18 | **Sentry scrubbing selhává** (unscrubbed paths/labels v UI) @ 2 týdny | 2026-04-24 23:25 | OK (verified po fix: message, tags, contexts všechny scrubnuté; geography fix přes "Prevent Storing of IP Addresses" zapnut user-side) |

**Most likely first triggers** (dle retrospektivy):

1. L-18 (Sentry scrubbing — file-heavy app privacy)
2. #3 (SPEC.md anchor dies pattern)
3. H-13 (Task Scheduler miss rate — Win stanice uptime issues)

---

## Token/context baseline

- **2026-04-24 pre-Superpowers-active (toggle off, skills nevidím):**
  - Total harness baseline: ~53.7k (z toho project overhead ~1.9k)
- **2026-04-24 post-Superpowers-active (Reload Window, skills exponovány):**
  - Total harness baseline: ~54.8k (z toho project + Superpowers overhead ~3.0k)
  - Superpowers contribution: **+1.1k tokens** (700 skills + 353 custom agent)
- **Target (rekalibrovaný):** project overhead < 15k nad Claude Code ~55k base. **Aktuální využití: 3.0k / 15k = 20% budgetu** — pohoda.

---

## Correction counter (kolo 1 kill criterion #1)

Po každé task v Claude Code poznamenej: task id, počet mých "no/přepiš/to není to co chci" korekcí.

| Date | Task | Corrections | Notes |
|------|------|-------------|-------|
| — | — | — | — |

---

## 2026-04-26 — Tray runtime pivot (SPEC v0.2 → v0.3)

**Brainstorm:** 5 otázek — Tray vs. Task Scheduler vztah (A: tray nahradí), auto-start (A: Task Scheduler At-log-on + restart), proces layout (B: tray + uvicorn one proces, UI okno subprocess), scheduler tech (B: threading.Thread + Event.wait smyčka), tray menu (A modified: Title + Open UI + Sync Now + Pause + Open log + Quit, 3-state ikona, toast jen errors s 30 min debounce).

**Spec:** [docs/superpowers/specs/2026-04-26-tray-design.md](docs/superpowers/specs/2026-04-26-tray-design.md)
**Plan:** [docs/superpowers/plans/2026-04-26-tray-runtime.md](docs/superpowers/plans/2026-04-26-tray-runtime.md)

**Reasoning:** v0 SPEC pivot — periodic Task Scheduler tick + manual `run-ui.bat` šel kolem viditelnosti stavu pro běžícího uživatele. Tray = single proces s viditelnou prezencí, instant "Sync Now", toast notifikace pro errors. Trade-off (sync stojí když tray neběží) mitigated Task Scheduler restart-on-failure.

**Watch items:** W-U6 (pystray+PyWebView coexistence neověřena na produkční mašině), W-U7 (subprocess cold start ≤ 3 s na pomalém disku — měřit success criterion #5), W-U8 (Task Scheduler At-log-on fast-logon edge — `-Delay PT30S` možný fallback).

**Migration pro existing users:** `git pull && pip install -e .[dev] && powershell scripts/install-task-scheduler.ps1 && logout && login`.

**Manual smoke 2026-04-26:**
- Tray icon visible in systray (rounded-square + sync-arrows glyph). ✅
- Quit ends process cleanly. ✅
- Open UI: spawns ui-window subprocess; PyWebView opens window with PlaudSync icon. ✅
- Double-click on tray icon = Open UI (default action). ✅
- Sync Now: bypasses schedule gate, runs pipeline (after `trigger='ui_sync_now'` fix for DB CHECK constraint). ✅
- Pause sync: gray icon + "Pause/Resume" toggle in menu. ✅
- Open log file: opens log via `notepad.exe` (os.startfile silently failed when .log had no default app). ✅
- "Last sync" in menu title reflects state.db `MAX(finished_at)` even after tray restart. ✅

**Production fixes applied during smoke:**
- `_allocate_port()`: pre-allocate uvicorn port via socket.bind(0) — `server.servers[0].sockets[0].getsockname()` was unreliable post-startup, fallback to port=0 caused ERR_CONNECTION_REFUSED in ui-window subprocess.
- `_configure_logging`: default log path now `state_root/.plaudsync/plaudsync.log` (was CWD/plaudsync.log → on_open_log looked at wrong path).
- `on_open_log`: switched from `os.startfile` to `subprocess.Popen([notepad.exe, log])` — .log has no default app on this machine.
- `_do_run(manual=True)`: temporarily sets `PLAUDSYNC_TRIGGER=ui_sync_now` so manual Sync Now bypasses schedule gate (was `"ui"` → DB CHECK constraint violation).
- `on_status_change`: `paused` added to valid icon states (was falling back to idle blue).
- Subprocess stdout/stderr now captured to `state_root/.plaudsync/ui-window.log` (was discarded → silent crash diagnosis impossible).
- ui-window subprocess uses `python.exe` (not pythonw) to retain stderr capture; trade-off: brief console flash at launch.

**Polished icons:** rounded-square background + state-specific glyph (sync-arrows / pause-bars / exclamation), running adds yellow pulse dot. `.ico` (multi-res 16/24/32/48/64) bundled at `src/plaudsync/ui/icon.ico` for window title bar.
