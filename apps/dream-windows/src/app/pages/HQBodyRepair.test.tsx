import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { HQJob } from "../../domain/hq-tryon";
import { hqApi } from "../../providers/hq-tryon-api";
import { HQBodyRepair } from "./HQBodyRepair";

const base: HQJob = { id: "hq-example", state: "succeeded", inputs: [] };
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("keeps the original when the scanner abstains and offers no derivative download", () => {
  render(<HQBodyRepair job={{ ...base, bodyRepair: { state: "unchanged" } }} original="blob:original" refresh={()=>{}} />);
  expect(screen.getByRole("status")).toHaveTextContent("保留原图");
  expect(screen.queryByRole("link", { name: "下载修整版" })).toBeNull();
});

it("does not show a download when a derivative fails verification", async () => {
  vi.spyOn(hqApi, "repairResult").mockRejectedValue(new Error("SHA-256 校验失败"));
  render(<HQBodyRepair job={{ ...base, bodyRepair: { state: "applied", sha256: "a".repeat(64) } }} original="blob:original" refresh={()=>{}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("校验失败");
  expect(screen.queryByRole("link", { name: "下载修整版" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "原始成片" }));
  expect(await screen.findByRole("img", { name: "修整前的原始成片" })).toHaveAttribute("src", "blob:original");
});

it("requests only the derived repair on a historical job", async () => {
  const scan=vi.spyOn(hqApi, "repair").mockResolvedValue(base), generate=vi.spyOn(hqApi,"create"), refresh=vi.fn();
  render(<HQBodyRepair job={base} original="blob:original" refresh={refresh} />);
  fireEvent.click(screen.getByRole("button", { name: "检查并修整此图" }));
  await waitFor(()=>expect(refresh).toHaveBeenCalledOnce());
  expect(scan).toHaveBeenCalledWith(base.id);expect(generate).not.toHaveBeenCalled();
});
