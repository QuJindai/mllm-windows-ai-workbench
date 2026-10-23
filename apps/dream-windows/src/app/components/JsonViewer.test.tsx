import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { JsonViewer } from "./JsonViewer";

it("keeps large raw research arrays in a single text node when highlighting is disabled", () => {
  const artifact = { values: Array.from({ length: 16384 }, (_, i) => i / 16384) };
  const { container } = render(<JsonViewer value={artifact} filename="research.json" highlight={false} />);
  fireEvent.click(screen.getByText(/展开原始记录/));
  const pre = container.querySelector("pre")!;
  expect(pre).toBeVisible();
  expect(JSON.parse(pre.textContent!)).toEqual(artifact);
  expect(pre.childElementCount).toBe(0);
});
