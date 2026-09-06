import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { DreamProviderContext } from "./app/providers";
import { MockDreamProvider } from "./providers/MockDreamProvider";
import "./styles/global.css";

const provider = new MockDreamProvider();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DreamProviderContext.Provider value={provider}>
      <App />
    </DreamProviderContext.Provider>
  </StrictMode>,
);
