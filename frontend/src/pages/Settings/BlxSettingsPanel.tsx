/**
 * BL-X Settings panel — structured form for waterfall classifier flags +
 * artifact toggles + folder catalog dropdown in projects table.
 *
 * Sits above the YAML ConfigPanel in the Settings page. On Save:
 *   1. Build ConfigParsedV4 from form state
 *   2. Serialize to YAML via serializeConfigV4
 *   3. PUT /api/config with the serialized YAML (re-uses existing endpoint)
 *   4. Surface X-Plaudsync-Warning header values as info banner
 *
 * The YAML editor below remains as advanced view — power users can edit
 * comments / unusual layouts there. After Save via this panel, the YAML
 * is canonicalized.
 */
import { useEffect, useMemo, useState } from "react";

import { ValidationError } from "@/api/client";
import { useFolders, useRefreshFolders, useSaveConfig } from "@/api/hooks";
import type { ConfigParsedV4, ProjectEntry } from "@/api/types";
import { useBanners } from "@/context/BannersContext";
import { useToasts } from "@/context/ToastsContext";
import { flagOrDefault, RECHECK_WINDOW_DAYS_DEFAULT, serializeConfigV4 } from "@/utils/configYaml";

interface Props {
  /** Coerced parsed config from current /api/config. */
  config: ConfigParsedV4;
  /** Refetch the parent useConfig() query — invoked after successful save
   * so YamlEditor below shows the canonicalized YAML. */
  onSaved: () => void;
}

interface FormState {
  download_audio: boolean;
  download_content: boolean;
  classify_by_name: boolean;
  classify_by_name_require_folder: boolean;
  classify_by_folder: boolean;
  sync_unclassified: boolean;
  recheck_window_days: number;
  /** Project name → ProjectEntry (preserves insertion order). */
  projects: Map<string, ProjectEntry>;
  unclassified_dir: string;
}

function _initFormState(config: ConfigParsedV4): FormState {
  const projects = new Map<string, ProjectEntry>();
  for (const [k, v] of Object.entries(config.projects)) {
    projects.set(k, { ...v });
  }
  return {
    download_audio: flagOrDefault(config, "download_audio"),
    download_content: flagOrDefault(config, "download_content"),
    classify_by_name: flagOrDefault(config, "classify_by_name"),
    classify_by_name_require_folder: flagOrDefault(
      config, "classify_by_name_require_folder",
    ),
    classify_by_folder: flagOrDefault(config, "classify_by_folder"),
    sync_unclassified: flagOrDefault(config, "sync_unclassified"),
    recheck_window_days: config.recheck_window_days ?? RECHECK_WINDOW_DAYS_DEFAULT,
    projects,
    unclassified_dir: config.unclassified_dir,
  };
}

function _formStateToConfig(state: FormState): ConfigParsedV4 {
  const projectsRecord: Record<string, ProjectEntry> = {};
  for (const [k, v] of state.projects) {
    projectsRecord[k] = v;
  }
  return {
    unclassified_dir: state.unclassified_dir,
    projects: projectsRecord,
    download_audio: state.download_audio,
    download_content: state.download_content,
    classify_by_name: state.classify_by_name,
    classify_by_name_require_folder: state.classify_by_name_require_folder,
    classify_by_folder: state.classify_by_folder,
    sync_unclassified: state.sync_unclassified,
    recheck_window_days: state.recheck_window_days,
  };
}

export default function BlxSettingsPanel({ config, onSaved }: Props) {
  const [state, setState] = useState<FormState>(() => _initFormState(config));
  const folders = useFolders();
  const refreshFolders = useRefreshFolders();
  const saveConfig = useSaveConfig();
  const { pushToast } = useToasts();
  const { pushBanner, dismissBanner } = useBanners();

  // Reset local form state when parent config refetches (e.g. after YAML
  // editor save below). Avoids stale form vs. canonicalized YAML.
  useEffect(() => {
    setState(_initFormState(config));
  }, [config]);

  const dirty = useMemo(() => {
    const initial = _initFormState(config);
    return JSON.stringify(_formStateToConfig(state))
      !== JSON.stringify(_formStateToConfig(initial));
  }, [state, config]);

  const onSave = () => {
    const yaml = serializeConfigV4(_formStateToConfig(state));
    saveConfig.mutate(yaml, {
      onSuccess: (data) => {
        const warnings = data.warnings;
        // Clear stale BL-X warning banners on every save — they re-attach
        // below if conditions still hold.
        dismissBanner("blx-no-artifacts");
        dismissBanner("blx-folder-not-in-catalog");

        if (warnings.includes("no-artifacts")) {
          pushBanner({
            id: "blx-no-artifacts",
            variant: "warning",
            title: "Sync neukládá žádné soubory",
            message:
              "Audio i textový obsah jsou vypnuté — recordings se evidují jen v databázi.",
          });
        }
        if (warnings.includes("folder-not-in-catalog")) {
          pushBanner({
            id: "blx-folder-not-in-catalog",
            variant: "warning",
            title: "Plaud složka mimo katalog",
            message:
              'Některý projekt odkazuje na složku, která není v aktuálním katalogu. Klikni „Načíst složky" níže pro refresh.',
          });
        }
        pushToast("success", "Konfigurace uložena");
        onSaved();
      },
      onError: (err) => {
        if (err instanceof ValidationError) {
          const first = err.errors[0];
          pushToast(
            "error",
            first
              ? `Konfigurace neuložena: ${first.message}`
              : "Konfigurace neuložena (validace).",
          );
          return;
        }
        pushToast("error", "Uložení selhalo — zkontroluj log");
      },
    });
  };

  const updateProject = (
    name: string,
    updater: (entry: ProjectEntry) => ProjectEntry,
  ) => {
    setState((s) => {
      const next = new Map(s.projects);
      const current = next.get(name);
      if (!current) return s;
      next.set(name, updater(current));
      return { ...s, projects: next };
    });
  };

  const renameProject = (oldName: string, newName: string) => {
    if (!newName || newName === oldName) return;
    setState((s) => {
      if (s.projects.has(newName)) return s;  // collision — block silently
      const next = new Map<string, ProjectEntry>();
      for (const [k, v] of s.projects) {
        next.set(k === oldName ? newName : k, v);
      }
      return { ...s, projects: next };
    });
  };

  const addProject = () => {
    setState((s) => {
      let n = 1;
      while (s.projects.has(`NEW_${n}`)) n++;
      const next = new Map(s.projects);
      next.set(`NEW_${n}`, { path: "", plaud_folder_id: null });
      return { ...s, projects: next };
    });
  };

  const removeProject = (name: string) => {
    setState((s) => {
      const next = new Map(s.projects);
      next.delete(name);
      return { ...s, projects: next };
    });
  };

  return (
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="p-5 border-b border-gray-100 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">
            Synchronizace a třídění
          </h2>
          <p className="text-[13px] text-gray-500 mt-1">
            Co stahovat (audio / textový obsah), kdy a jak třídit. Po
            uložení se YAML níže zaktualizuje automaticky.
          </p>
        </div>
        <button
          type="button"
          disabled={!dirty || saveConfig.isPending}
          onClick={onSave}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white shadow-sm disabled:opacity-50"
        >
          {saveConfig.isPending ? "Ukládám…" : "Uložit"}
        </button>
      </div>

      <div className="p-5 space-y-6">
        {/* ----- Co stahovat ----- */}
        <fieldset className="space-y-2">
          <legend className="text-[13px] font-medium text-gray-800 mb-1">
            Co stahovat
          </legend>
          <CheckboxRow
            id="bl4-audio"
            checked={state.download_audio}
            onChange={(checked) =>
              setState((s) => ({ ...s, download_audio: checked }))
            }
            label="Audio (MP3)"
            description="Originální zvukový záznam."
          />
          <CheckboxRow
            id="bl4-content"
            checked={state.download_content}
            onChange={(checked) =>
              setState((s) => ({ ...s, download_content: checked }))
            }
            label="Textový obsah (.md)"
            description="Sumarizace + osnova + transkript jako sourozenec MP3 (jeden Markdown soubor)."
          />
          {!state.download_audio && !state.download_content && (
            <div className="text-[12px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-3 py-2">
              Žádný artefakt vybraný — recordings se budou jen evidovat v DB
              bez ukládání souborů.
            </div>
          )}
        </fieldset>

        {/* ----- Jak třídit a co synchronizovat ----- */}
        <fieldset className="space-y-2">
          <legend className="text-[13px] font-medium text-gray-800 mb-1">
            Jak třídit a co synchronizovat
          </legend>
          <CheckboxRow
            id="bl4-classify-name"
            checked={state.classify_by_name}
            onChange={(checked) =>
              setState((s) => ({ ...s, classify_by_name: checked }))
            }
            label="Třídit podle projektu v názvu"
            description='Regex match na titulu (formát "MM-DD KOD: …" nebo "YYYY-MM-DD KOD: …").'
          />
          {state.classify_by_name && (
            <div className="ml-7">
              <CheckboxRow
                id="bl4-require-folder"
                checked={state.classify_by_name_require_folder}
                onChange={(checked) =>
                  setState((s) => ({
                    ...s,
                    classify_by_name_require_folder: checked,
                  }))
                }
                label="Pouze pokud je zároveň ve složce na Plaude"
                description="Defenzivně proti random titulům — match honorován jen když má i Plaud folder."
              />
            </div>
          )}
          <CheckboxRow
            id="bl4-classify-folder"
            checked={state.classify_by_folder}
            onChange={(checked) =>
              setState((s) => ({ ...s, classify_by_folder: checked }))
            }
            label="Třídit podle složky na Plaude"
            description="Fallback když název nematched. Vyžaduje přiřazení Plaud složky k projektu níže."
          />
          <CheckboxRow
            id="bl4-sync-unclassified"
            checked={state.sync_unclassified}
            onChange={(checked) =>
              setState((s) => ({ ...s, sync_unclassified: checked }))
            }
            label="Synchronizovat i to, co nelze roztřídit"
            description="Catch-all do složky pro neklasifikované. Textový obsah se pro neklasifikované nikdy nestahuje."
          />
          {!state.classify_by_name
            && !state.classify_by_folder
            && !state.sync_unclassified && (
            <div className="text-[12px] text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">
              Alespoň jedna strategie musí být aktivní — jinak Save selže.
            </div>
          )}
          <label className="block pt-1">
            <span className="text-[13px] text-gray-800">
              Re-kontrolovat záznamy zpětně (dní)
            </span>
            <p className="text-[12px] text-gray-500 mt-0.5">
              Jak daleko zpět se přehodnocují přeskočené záznamy (přejmenování,
              přesun složky, přidání projektu). Starší se už nezpracovávají.
            </p>
            <input
              type="number"
              min={1}
              value={state.recheck_window_days}
              onChange={(e) =>
                setState((s) => ({
                  ...s,
                  recheck_window_days: Math.max(1, Number(e.target.value) || 1),
                }))
              }
              className="mt-1 w-28 rounded-md border-gray-300 text-sm"
            />
          </label>
        </fieldset>

        {/* ----- Cesty na disk ----- */}
        <fieldset className="space-y-3">
          <legend className="text-[13px] font-medium text-gray-800 mb-1">
            Cesty na disk
          </legend>
          <label className="block">
            <span className="text-[12px] text-gray-700">
              Složka pro neklasifikované záznamy
            </span>
            <input
              type="text"
              value={state.unclassified_dir}
              onChange={(e) =>
                setState((s) => ({ ...s, unclassified_dir: e.target.value }))
              }
              placeholder="C:\Plaud\Unclassified"
              className="mt-1 w-full rounded-md border-gray-300 text-sm font-mono"
            />
          </label>
          <ProjectsTable
            projects={state.projects}
            folders={folders.data?.folders ?? []}
            classifyByFolder={state.classify_by_folder}
            onRename={renameProject}
            onUpdate={updateProject}
            onAdd={addProject}
            onRemove={removeProject}
          />
          <FolderCatalogStatus
            folders={folders.data}
            isFetching={folders.isFetching}
            isRefreshing={refreshFolders.isPending}
            onRefresh={() =>
              refreshFolders.mutate(undefined, {
                onSuccess: () =>
                  pushToast(
                    "success",
                    `Načteno složek z Plaude: ${folders.data?.folders.length ?? 0}`,
                  ),
                onError: () =>
                  pushToast(
                    "error",
                    "Nepodařilo se načíst složky z Plaude (token / region?).",
                  ),
              })
            }
          />
        </fieldset>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function CheckboxRow(props: {
  id: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}) {
  return (
    <label
      htmlFor={props.id}
      className="flex items-start gap-3 cursor-pointer select-none"
    >
      <input
        id={props.id}
        type="checkbox"
        checked={props.checked}
        disabled={props.disabled}
        onChange={(e) => props.onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
      />
      <div className="flex-1">
        <div className="text-[13px] text-gray-800">{props.label}</div>
        {props.description && (
          <div className="text-[12px] text-gray-500 mt-0.5">
            {props.description}
          </div>
        )}
      </div>
    </label>
  );
}

function ProjectsTable(props: {
  projects: Map<string, ProjectEntry>;
  folders: { id: string; name: string }[];
  classifyByFolder: boolean;
  onRename: (oldName: string, newName: string) => void;
  onUpdate: (name: string, updater: (e: ProjectEntry) => ProjectEntry) => void;
  onAdd: () => void;
  onRemove: (name: string) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[12px] text-gray-700">Projekty</span>
        <button
          type="button"
          onClick={props.onAdd}
          className="text-[12px] text-blue-600 hover:text-blue-700"
        >
          + Přidat projekt
        </button>
      </div>
      {props.projects.size === 0 ? (
        <p className="text-[12px] text-gray-400 italic">
          Žádný projekt nakonfigurován.
        </p>
      ) : (
        <div className="border border-gray-200 rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-[11px] uppercase">
              <tr>
                <th className="text-left px-3 py-1.5 font-medium">Kód</th>
                <th className="text-left px-3 py-1.5 font-medium">
                  Cílová cesta
                </th>
                <th className="text-left px-3 py-1.5 font-medium">
                  Plaud složka
                </th>
                <th className="px-2 py-1.5 w-8" />
              </tr>
            </thead>
            <tbody>
              {[...props.projects.entries()].map(([name, entry]) => (
                <tr key={name} className="border-t border-gray-200">
                  <td className="px-3 py-1.5">
                    <input
                      type="text"
                      defaultValue={name}
                      onBlur={(e) => props.onRename(name, e.target.value.trim())}
                      className="w-full text-sm font-mono border-0 bg-transparent focus:ring-0 px-0"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      type="text"
                      value={entry.path}
                      onChange={(e) =>
                        props.onUpdate(name, (en) => ({
                          ...en,
                          path: e.target.value,
                        }))
                      }
                      placeholder="C:\Projekty\…"
                      className="w-full text-sm font-mono border-0 bg-transparent focus:ring-0 px-0"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <select
                      value={entry.plaud_folder_id ?? ""}
                      onChange={(e) =>
                        props.onUpdate(name, (en) => ({
                          ...en,
                          plaud_folder_id: e.target.value || null,
                        }))
                      }
                      disabled={!props.classifyByFolder}
                      className="w-full text-sm border-0 bg-transparent focus:ring-0 px-0 disabled:text-gray-400"
                    >
                      <option value="">— žádná —</option>
                      {props.folders.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))}
                      {/* Preserve existing folder_id even if not in current
                          catalog — server will surface 'folder-not-in-catalog'
                          warning so user can refresh. */}
                      {entry.plaud_folder_id
                        && !props.folders.some((f) => f.id === entry.plaud_folder_id)
                        && (
                        <option value={entry.plaud_folder_id}>
                          {entry.plaud_folder_id.slice(0, 8)}… (mimo katalog)
                        </option>
                      )}
                    </select>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <button
                      type="button"
                      onClick={() => props.onRemove(name)}
                      title="Smazat projekt"
                      className="text-gray-400 hover:text-red-600 text-lg leading-none"
                    >
                      ×
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FolderCatalogStatus(props: {
  folders: { folders: unknown[]; fetched_at: string | null; stale: boolean } | undefined;
  isFetching: boolean;
  isRefreshing: boolean;
  onRefresh: () => void;
}) {
  const fetchedAt = props.folders?.fetched_at;
  const count = props.folders?.folders.length ?? 0;
  const stale = props.folders?.stale ?? true;

  return (
    <div className="flex items-center justify-between gap-3 text-[12px] text-gray-600 border-t border-gray-100 pt-3">
      <div>
        {fetchedAt ? (
          <span>
            Katalog složek: <strong>{count}</strong> položek
            {stale && (
              <span className="text-amber-700 ml-2">(zastaralé &gt; 1 h)</span>
            )}
          </span>
        ) : (
          <span className="text-gray-400">
            Katalog složek nebyl ještě načten z Plaude.
          </span>
        )}
      </div>
      <button
        type="button"
        onClick={props.onRefresh}
        disabled={props.isFetching || props.isRefreshing}
        className="text-blue-600 hover:text-blue-700 disabled:opacity-50"
      >
        {props.isRefreshing ? "Načítám…" : "Načíst složky"}
      </button>
    </div>
  );
}
