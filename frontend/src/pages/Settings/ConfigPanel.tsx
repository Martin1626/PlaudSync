import { useEffect, useMemo, useRef, useState } from "react";

import { ValidationError } from "@/api/client";
import { useConfig, useSaveConfig } from "@/api/hooks";
import type { ConfigParseError, ConfigResponse } from "@/api/types";
import { useToasts } from "@/context/ToastsContext";

import YamlEditor from "./YamlEditor";

export default function ConfigPanel({ config }: { config: ConfigResponse }) {
  const refetch = useConfig().refetch;
  const saveConfig = useSaveConfig();
  const { pushToast } = useToasts();

  const [yaml, setYaml] = useState(config.raw_yaml);
  const lastSavedRef = useRef(config.raw_yaml);
  const [errors, setErrors] = useState<ConfigParseError[]>(() =>
    config.parse_error ? [config.parse_error] : [],
  );
  const [currentErrorIndex, setCurrentErrorIndex] = useState(
    config.parse_error ? 0 : -1,
  );

  // If incoming config changes (after refetch), reset local edits to server YAML.
  useEffect(() => {
    setYaml(config.raw_yaml);
    lastSavedRef.current = config.raw_yaml;
    if (config.parse_error) {
      setErrors([config.parse_error]);
      setCurrentErrorIndex(0);
      pushToast(
        "error",
        `Existující konfigurace je neplatná — řádek ${config.parse_error.line}`,
      );
    } else {
      setErrors([]);
      setCurrentErrorIndex(-1);
    }
  }, [config, pushToast]);

  const dirty = useMemo(() => yaml !== lastSavedRef.current, [yaml]);

  const onChangeYaml = (next: string) => {
    setYaml(next);
    if (errors.length > 0) {
      // Editing clears stale errors — re-save will re-validate.
      setErrors([]);
      setCurrentErrorIndex(-1);
    }
  };

  const onSave = () => {
    saveConfig.mutate(yaml, {
      onSuccess: () => {
        lastSavedRef.current = yaml;
        setErrors([]);
        setCurrentErrorIndex(-1);
        pushToast("success", "Konfigurace uložena");
      },
      onError: (err) => {
        if (err instanceof ValidationError) {
          setErrors(err.errors);
          setCurrentErrorIndex(0);
          const first = err.errors[0];
          pushToast(
            "error",
            first && first.line > 0
              ? `Konfigurace je neplatná — řádek ${first.line}`
              : "Konfigurace je neplatná",
          );
          return;
        }
        pushToast("error", "Uložení selhalo — zkontroluj log");
      },
    });
  };

  const onReload = () => {
    if (dirty) {
      const ok = window.confirm("Zahodit neuložené změny?");
      if (!ok) return;
    }
    void refetch().then(() => {
      pushToast("success", "Konfigurace načtena znovu");
    });
  };

  const lineCount = yaml.split("\n").length;

  return (
    <section className="bg-white rounded-lg border border-gray-200 shadow-sm">
      <div className="p-5 border-b border-gray-100 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Konfigurace</h2>
          <p className="text-[13px] text-gray-500 mt-1">
            YAML soubor v{" "}
            <span className="font-mono text-gray-700">
              $PLAUDSYNC_STATE_ROOT\config.yaml
            </span>
            .
          </p>
        </div>
      </div>
      <div className="p-5 space-y-4">
        <YamlEditor
          value={yaml}
          onChange={onChangeYaml}
          errors={errors}
          currentErrorIndex={currentErrorIndex}
          onSelectError={setCurrentErrorIndex}
        />
        <div className="flex items-center gap-3">
          <button
            type="button"
            disabled={saveConfig.isPending}
            onClick={onSave}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white shadow-sm disabled:opacity-60"
          >
            {saveConfig.isPending ? (
              <svg
                viewBox="0 0 24 24"
                className="w-4 h-4 animate-spin"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                aria-hidden="true"
              >
                <path d="M21 12a9 9 0 1 1-6.2-8.55" />
              </svg>
            ) : (
              <svg
                viewBox="0 0 24 24"
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                <path d="M17 21v-8H7v8M7 3v5h8" />
              </svg>
            )}
            Uložit
          </button>
          <button
            type="button"
            onClick={onReload}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-md text-sm font-medium border border-gray-200 bg-white hover:bg-gray-50 text-gray-700"
          >
            <svg
              viewBox="0 0 24 24"
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M3 12a9 9 0 0 1 15.5-6.3L21 8" />
              <path d="M21 4v4h-4" />
            </svg>
            Načíst znovu
          </button>
          <span className="ml-auto text-xs text-gray-400 font-mono">
            {lineCount} řádků
          </span>
        </div>
      </div>
    </section>
  );
}
