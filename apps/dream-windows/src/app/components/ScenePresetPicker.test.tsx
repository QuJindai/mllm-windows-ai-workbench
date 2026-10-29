import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScenePresetPicker } from "./ScenePresetPicker";

describe("Scene presets", () => {
  it.each(["古风", "女帝", "公主", "科幻"])("applies each framing to %s without contradictory crops or automatic edits", (name) => {
    const onApply = vi.fn();
    render(<ScenePresetPicker modelId="realistic-vision-v5.1-faceid" prompt="draft" negativePrompt="excluded" onApply={onApply} />);
    for (const [framing, included, excluded] of [
      ["portrait", "head and shoulders", /medium shot|waist-up|full body/],
      ["half", "waist-up", /head and shoulders|full body/],
      ["full", "full body", /medium shot|waist-up|portrait photo/],
    ] as const) {
      const previousCalls = onApply.mock.calls.length;
      fireEvent.change(screen.getByRole("combobox", { name: "场景构图" }), { target: { value: framing } });
      expect(onApply).toHaveBeenCalledTimes(previousCalls);
      fireEvent.click(screen.getByRole("button", { name: `应用${name}场景` }));
      const replacement = onApply.mock.lastCall![0];
      expect(replacement.prompt).toContain(included);
      expect(replacement.prompt).not.toMatch(excluded);
      if (framing === "portrait") expect(replacement.negativePrompt).not.toContain("close-up");
      if (framing === "full") expect(replacement.prompt).toContain("feet in frame");
      expect(Object.keys(replacement).sort()).toEqual(["negativePrompt", "prompt"]);
    }
    expect(screen.getByText(/文本构图提示.*骨架约束/)).toBeVisible();
  });

  it.each([
    ["realistic-vision-v5.1-faceid", { width: 512, height: 768, steps: 28, cfg: 5.5 }],
    ["illustrious-xl-v2.0-faceid", { width: 768, height: 768, steps: 30, cfg: 5 }],
    ["cyberrealistic-xl-plus-face", { width: 768, height: 768, steps: 30, cfg: 5 }],
    ["cyberrealistic-xl-v10-standard", { width: 768, height: 768, steps: 20, cfg: 4 }],
    ["illustrious-xl-v2.0", { width: 1024, height: 1024, steps: 30, cfg: 7 }],
    ["animagine-xl-4.0-opt-standard", { width: 768, height: 768, steps: 28, cfg: 5 }],
    ["dreamshaper-xl-lightning", { width: 768, height: 768, steps: 8, cfg: 2 }],
  ])("applies only size, steps and CFG for %s after a separate explicit action", (modelId, expected) => {
    const onApply = vi.fn(), onApplyRecipe = vi.fn();
    render(<ScenePresetPicker modelId={modelId as string} prompt="draft" negativePrompt="excluded" modelReady onApply={onApply} onApplyRecipe={onApplyRecipe} />);
    fireEvent.click(screen.getByRole("button", { name: "应用公主场景" }));
    expect(onApplyRecipe).not.toHaveBeenCalled();
    onApply.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "应用模型推荐参数" }));
    expect(onApplyRecipe).toHaveBeenCalledExactlyOnceWith(expected);
    expect(onApply).not.toHaveBeenCalled();
  });

  it("keeps prompt undo available after explicitly applying a recipe", () => {
    const onApply = vi.fn(), onApplyRecipe = vi.fn();
    const props = { modelId: "cyberrealistic-xl-v10-standard", modelReady: true, onApply, onApplyRecipe };
    const view = render(<ScenePresetPicker {...props} prompt="draft" negativePrompt="excluded" />);
    fireEvent.click(screen.getByRole("button", { name: "应用女帝场景" }));
    view.rerender(<ScenePresetPicker {...props} {...onApply.mock.lastCall![0]} />);
    fireEvent.click(screen.getByRole("button", { name: "应用模型推荐参数" }));
    fireEvent.click(screen.getByRole("button", { name: "撤销场景替换" }));
    expect(onApply).toHaveBeenLastCalledWith({ prompt: "draft", negativePrompt: "excluded" });
    expect(onApplyRecipe).toHaveBeenCalledTimes(1);
  });

  it("blocks mismatched and unavailable recipes without blocking prompt-only use or silently switching models", () => {
    const onApply = vi.fn(), onApplyRecipe = vi.fn();
    const props = { prompt: "draft", negativePrompt: "excluded", onApply, onApplyRecipe };
    const view = render(<ScenePresetPicker {...props} modelId="cyberrealistic-xl-v10-standard" modelReady />);
    fireEvent.change(screen.getByRole("combobox", { name: "场景画风" }), { target: { value: "anime" } });
    expect(screen.getByRole("button", { name: "应用模型推荐参数" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "应用公主场景" }));
    expect(onApply.mock.lastCall![0].prompt).toContain("anime illustration");
    view.rerender(<ScenePresetPicker {...props} modelId="illustrious-xl-v2.0-plus-face" modelReady={false} />);
    expect(screen.getByRole("button", { name: "应用模型推荐参数" })).toBeDisabled();
    view.rerender(<ScenePresetPicker {...props} modelId="unregistered-model" modelReady />);
    expect(screen.getByRole("button", { name: "应用模型推荐参数" })).toBeDisabled();
    expect(onApplyRecipe).not.toHaveBeenCalled();
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("uses the current registered defaults and freezes all recipe controls during generation", () => {
    const onApply = vi.fn(), onApplyRecipe = vi.fn();
    const props = { modelId: "illustrious-xl-v2.0", prompt: "draft", negativePrompt: "excluded", modelReady: true, onApply, onApplyRecipe,
      recipeDefaults: { width: 768, height: 1024, steps: 32, cfg: 6 } };
    const view = render(<ScenePresetPicker {...props} />);
    expect(screen.getByText(/768 × 1024.*32.*CFG 6/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "应用模型推荐参数" }));
    expect(onApplyRecipe).toHaveBeenCalledExactlyOnceWith({ width: 768, height: 1024, steps: 32, cfg: 6 });
    view.rerender(<ScenePresetPicker {...props} disabled />);
    expect(screen.getByRole("combobox", { name: "场景构图" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "应用模型推荐参数" })).toBeDisabled();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("includes scene-specific exclusions together with the selected style", () => {
    const onApply = vi.fn();
    render(<ScenePresetPicker modelId="realistic-vision-v5.1-faceid" prompt="" negativePrompt="" onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "应用科幻场景" }));
    const replacement = onApply.mock.calls[0][0];
    expect(replacement.negativePrompt).toContain("helmet");
    expect(replacement.negativePrompt).toContain("cartoon");
  });
  it("only replaces prompts on explicit selection and can undo the replacement", () => {
    const onApply = vi.fn();
    const original = { prompt: "my own scene", negativePrompt: "my exclusions" };
    const view = render(<ScenePresetPicker modelId="realistic-vision-v5.1-faceid" {...original} onApply={onApply} />);
    expect(onApply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "应用女帝场景" }));
    const replacement = onApply.mock.calls[0][0];
    expect(replacement.prompt).toContain("imperial throne");
    expect(replacement.prompt).toContain("realistic");
    expect(Object.keys(replacement).sort()).toEqual(["negativePrompt", "prompt"]);
    view.rerender(<ScenePresetPicker modelId="realistic-vision-v5.1-faceid" {...replacement} onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "撤销场景替换" }));
    expect(onApply).toHaveBeenLastCalledWith(original);
  });

  it("suggests anime for an anime model without silently replacing text when the model changes", () => {
    const onApply = vi.fn();
    const props = { prompt: "keep draft", negativePrompt: "keep exclusions", onApply };
    const view = render(<ScenePresetPicker modelId="realistic-vision-v5.1-faceid" {...props} />);
    view.rerender(<ScenePresetPicker modelId="illustrious-xl-v2.0-faceid" {...props} />);
    expect(screen.getByRole("combobox", { name: "场景画风" })).toHaveValue("anime");
    expect(onApply).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "应用公主场景" }));
    expect(onApply.mock.calls[0][0].prompt).toContain("anime illustration");
    expect(onApply.mock.calls[0][0].prompt).toContain("adult princess");
  });

  it("locks scene changes while generating and does not offer stale undo after manual edits", () => {
    const onApply = vi.fn();
    const view = render(<ScenePresetPicker modelId="cyberrealistic-xl-v10-standard" prompt="old" negativePrompt="old" onApply={onApply} />);
    fireEvent.click(screen.getByRole("button", { name: "应用科幻场景" }));
    view.rerender(<ScenePresetPicker modelId="cyberrealistic-xl-v10-standard" prompt="manual edit" negativePrompt="old" onApply={onApply} disabled />);
    expect(screen.getByRole("button", { name: "应用古风场景" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "场景画风" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "撤销场景替换" })).not.toBeInTheDocument();
  });
});
