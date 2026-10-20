import { useEffect, useRef } from "react";
import { basicSetup } from "codemirror";
import { EditorState, Compartment } from "@codemirror/state";
import { Decoration, EditorView, keymap } from "@codemirror/view";
import { indentWithTab } from "@codemirror/commands";
import { indentUnit, HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { yaml } from "@codemirror/lang-yaml";
import { tags } from "@lezer/highlight";

interface Props {
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  /** Ctrl+S / ⌘S внутри редактора */
  onSave?: () => void;
  /** Подсветить строку (1-based) — например, строку ошибки YAML */
  errorLine?: number | null;
  className?: string;
  ariaLabel?: string;
}

// Цвета — из токенов темы (index.css, --c-code-*): редактор следует светлой и тёмной теме сам
const highlight = HighlightStyle.define([
  { tag: [tags.propertyName, tags.definition(tags.propertyName)], color: "rgb(var(--c-code-key))" },
  { tag: [tags.string, tags.special(tags.string), tags.content], color: "rgb(var(--c-code-string))" },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: "rgb(var(--c-code-number))" },
  { tag: [tags.keyword, tags.meta, tags.labelName, tags.typeName], color: "rgb(var(--c-code-keyword))" },
  { tag: tags.comment, color: "rgb(var(--c-subtle))", fontStyle: "italic" },
  { tag: [tags.punctuation, tags.separator], color: "rgb(var(--c-muted-foreground))" },
]);

const theme = EditorView.theme({
  "&": { height: "100%", fontSize: "13px", backgroundColor: "rgb(var(--c-surface))", color: "rgb(var(--c-foreground))" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", lineHeight: "1.6" },
  ".cm-content": { caretColor: "rgb(59 130 246)", padding: "8px 0" },
  ".cm-cursor": { borderLeftColor: "rgb(59 130 246)", borderLeftWidth: "2px" },
  ".cm-gutters": { backgroundColor: "rgb(var(--c-muted) / 0.5)", color: "rgb(var(--c-subtle))", border: "none", borderRight: "1px solid rgb(var(--c-border))" },
  ".cm-activeLineGutter": { backgroundColor: "rgb(var(--c-muted))", color: "rgb(var(--c-foreground))" },
  ".cm-activeLine": { backgroundColor: "rgb(var(--c-muted) / 0.45)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": { backgroundColor: "rgb(59 130 246 / 0.25) !important" },
  ".cm-selectionMatch": { backgroundColor: "rgb(59 130 246 / 0.12)" },
  ".cm-matchingBracket": { backgroundColor: "rgb(59 130 246 / 0.18)", outline: "none" },
  ".cm-foldPlaceholder": { backgroundColor: "rgb(var(--c-muted))", border: "none", color: "rgb(var(--c-muted-foreground))" },
  ".cm-tooltip": { backgroundColor: "rgb(var(--c-surface))", border: "1px solid rgb(var(--c-border))", borderRadius: "8px" },
  ".cm-tooltip-autocomplete ul li[aria-selected]": { backgroundColor: "rgb(59 130 246 / 0.15)", color: "rgb(var(--c-foreground))" },
  ".cm-panels": { backgroundColor: "rgb(var(--c-muted))", color: "rgb(var(--c-foreground))" },
  ".cm-panels input, .cm-panels button": { fontSize: "12px" },
  ".cm-error-line": { backgroundColor: "rgb(244 63 94 / 0.14)" },
});

/** Строка с ошибкой — декорация класса строки, без отдельного lint-пакета */
function errorLineExtension(line: number | null | undefined) {
  if (!line) return [];
  return EditorView.decorations.compute(["doc"], (state) =>
    line > state.doc.lines ? Decoration.none : Decoration.set([Decoration.line({ class: "cm-error-line" }).range(state.doc.line(line).from)]),
  );
}

/** Редактор YAML на CodeMirror 6: подсветка, номера строк, сворачивание, поиск (Ctrl+F), Tab — отступ. */
export default function YamlEditor({ value, onChange, readOnly = false, onSave, errorLine, className = "", ariaLabel = "Текст плейбука" }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const handlers = useRef({ onChange, onSave });
  handlers.current = { onChange, onSave };
  const readOnlyConf = useRef(new Compartment());
  const errorConf = useRef(new Compartment());

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          yaml(),
          indentUnit.of("  "),
          EditorState.tabSize.of(2),
          keymap.of([
            indentWithTab,
            { key: "Mod-s", preventDefault: true, run: () => (handlers.current.onSave?.(), true) },
          ]),
          syntaxHighlighting(highlight),
          theme,
          readOnlyConf.current.of([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)]),
          errorConf.current.of(errorLineExtension(errorLine)),
          EditorView.contentAttributes.of({ "aria-label": ariaLabel, spellcheck: "false" }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) handlers.current.onChange?.(update.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // Создаётся один раз; дальше value, readOnly и строка ошибки приходят через эффекты ниже
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Текст пришёл снаружи (загрузка файла, «копия в локальные») — заменить документ целиком
  useEffect(() => {
    const editor = view.current;
    if (editor && value !== editor.state.doc.toString()) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    view.current?.dispatch({ effects: readOnlyConf.current.reconfigure([EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly)]) });
  }, [readOnly]);

  useEffect(() => {
    view.current?.dispatch({ effects: errorConf.current.reconfigure(errorLineExtension(errorLine)) });
  }, [errorLine]);

  return <div ref={host} className={`overflow-hidden ${className}`} />;
}
