import { useCallback, useEffect, useState } from "react";
import { fetchUi, listPipelines, listSections, type PipelineInfo, type SectionInfo, type UiView } from "./api";
import { PipelineView } from "./pipeline";
import { SpecsView } from "./specs";

type Level = "pipeline" | "specs";
const LEVELS: Level[] = ["pipeline", "specs"];

export function App() {
  const [ui, setUi] = useState<UiView | null>(null);
  const [pipelines, setPipelines] = useState<PipelineInfo[]>([]);
  const [sections, setSections] = useState<SectionInfo[]>([]);
  const [level, setLevel] = useState<Level>("pipeline");
  const [selected, setSelected] = useState("");
  const [focus, setFocus] = useState({ pipeline: "", section: "" });

  useEffect(() => {
    Promise.all([fetchUi(), listPipelines(), listSections()]).then(([view, found, mounted]) => {
      setUi(view);
      setPipelines(found);
      setSections(mounted);
      setSelected(found[0]?.id ?? "");
    });
  }, []);

  const pick = useCallback(
    (pipeline: string, section: string) => {
      const first = sections.find((found) => found.pipeline === pipeline)?.section ?? "";
      setFocus({ pipeline, section: section || first });
    },
    [sections],
  );

  const enter = useCallback(
    (next: Level) => {
      if (next === "specs" && focus.pipeline !== selected) pick(selected, "");
      setLevel(next);
    },
    [focus.pipeline, selected, pick],
  );

  const open = useCallback(
    (pipeline: string, section: string) => {
      pick(pipeline, section);
      setLevel("specs");
    },
    [pick],
  );

  if (ui === null) return null;
  const levels = (
    <div className="levels" role="tablist" aria-label="level">
      {LEVELS.map((name) => (
        <button
          key={name}
          type="button"
          role="tab"
          aria-selected={level === name}
          className={level === name ? "tab tab-on" : "tab"}
          onClick={() => enter(name)}
        >
          {name}
        </button>
      ))}
    </div>
  );
  return level === "pipeline" ? (
    <PipelineView
      ui={ui}
      pipelines={pipelines}
      selected={selected}
      setSelected={setSelected}
      levels={levels}
      onOpen={open}
    />
  ) : (
    <SpecsView
      ui={ui}
      sections={sections}
      pipeline={focus.pipeline}
      section={focus.section}
      onPick={pick}
      levels={levels}
    />
  );
}
