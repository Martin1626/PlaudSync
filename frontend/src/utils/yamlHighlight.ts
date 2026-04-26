// Minimal YAML tokenizer for the Settings editor overlay.
// Token classes map to .yh-* CSS rules in index.css.
//
// Scope: keys, scalar values (strings / numbers / bools / null), comments,
// block-sequence dashes, ${VAR} interpolation, and indentation. Anchors,
// aliases, tags, multi-line block scalars (>, |) are out of scope — the
// PlaudSync config schema uses only flat key/value/string entries.

type Cls =
  | "key"
  | "punct"
  | "string"
  | "number"
  | "bool"
  | "null"
  | "var"
  | "comment"
  | "dash"
  | "plain";

interface Span {
  cls: Cls;
  text: string;
}

const escapeHtml = (s: string): string =>
  s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

// Inject ${VAR} highlighting into a plain-string region.
function splitVars(text: string, baseCls: Cls): Span[] {
  const out: Span[] = [];
  const re = /\$\{[A-Za-z_][A-Za-z0-9_]*\}/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      out.push({ cls: baseCls, text: text.slice(last, m.index) });
    }
    out.push({ cls: "var", text: m[0] });
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    out.push({ cls: baseCls, text: text.slice(last) });
  }
  return out;
}

function classifyScalar(value: string): Cls {
  const trimmed = value.trim();
  if (trimmed === "") return "plain";
  if (/^(true|false|yes|no|on|off)$/i.test(trimmed)) return "bool";
  if (/^(null|~)$/i.test(trimmed)) return "null";
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return "number";
  if (/^["'].*["']$/.test(trimmed)) return "string";
  return "plain";
}

function tokenizeLine(line: string): Span[] {
  const spans: Span[] = [];

  // Comment-only line (with optional leading whitespace).
  if (/^\s*#/.test(line)) {
    return [{ cls: "comment", text: line }];
  }

  // Leading whitespace + optional block-sequence dash.
  const lead = /^(\s*)(-\s+)?/.exec(line)!;
  const indent = lead[1] ?? "";
  const dash = lead[2] ?? "";
  let rest = line.slice(indent.length + dash.length);

  if (indent) spans.push({ cls: "plain", text: indent });
  if (dash) spans.push({ cls: "dash", text: dash });

  // Trailing inline comment (only if # is preceded by whitespace).
  let trailingComment = "";
  const commentMatch = /(\s+)#.*$/.exec(rest);
  if (commentMatch) {
    trailingComment = rest.slice(commentMatch.index);
    rest = rest.slice(0, commentMatch.index);
  }

  // key: value  (key may include unicode word chars + spaces, no leading whitespace here)
  const kv = /^([^:#\s][^:#]*?)(\s*):(\s+|$)(.*)$/.exec(rest);
  if (kv) {
    const [, key, padBefore, padAfter, value] = kv;
    spans.push({ cls: "key", text: key! });
    if (padBefore) spans.push({ cls: "plain", text: padBefore });
    spans.push({ cls: "punct", text: ":" });
    if (padAfter) spans.push({ cls: "plain", text: padAfter });
    if (value && value.length > 0) {
      const cls = classifyScalar(value);
      // Variables ${X} can appear in plain-string scalars; split them.
      if (cls === "string" || cls === "plain") {
        spans.push(...splitVars(value, cls));
      } else {
        spans.push({ cls, text: value });
      }
    }
  } else if (rest.length > 0) {
    // Bare scalar (e.g., list item value after dash).
    const cls = classifyScalar(rest);
    if (cls === "string" || cls === "plain") {
      spans.push(...splitVars(rest, cls));
    } else {
      spans.push({ cls, text: rest });
    }
  }

  if (trailingComment) {
    spans.push({ cls: "comment", text: trailingComment });
  }

  return spans;
}

export function highlightYaml(source: string): string {
  // Render line-by-line; preserve trailing newline so the overlay's height
  // matches the textarea exactly (textarea also keeps the final empty line).
  const lines = source.split("\n");
  const html = lines
    .map((line) => {
      if (line.length === 0) {
        // Empty line — emit a zero-width space so the line still occupies a row.
        return "​";
      }
      return tokenizeLine(line)
        .map((s) => `<span class="yh-${s.cls}">${escapeHtml(s.text)}</span>`)
        .join("");
    })
    .join("\n");
  return html;
}
