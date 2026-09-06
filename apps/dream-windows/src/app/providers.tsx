import { createContext, useContext } from "react";
import type { DreamProvider } from "../providers/DreamProvider";

export const DreamProviderContext = createContext<DreamProvider | null>(null);

export function useDreamProvider(): DreamProvider {
  const provider = useContext(DreamProviderContext);
  if (!provider) throw new Error("DreamProviderContext is missing");
  return provider;
}
