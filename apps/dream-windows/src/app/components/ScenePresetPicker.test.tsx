import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScenePresetPicker } from "./ScenePresetPicker";

describe("Scene presets", () => {
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
