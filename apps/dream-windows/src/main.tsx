import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { DreamProviderContext } from "./app/providers";
import { createDreamProvider } from "./providers/DreamHttpProvider";
import "./styles/global.css";

const provider = createDreamProvider();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DreamProviderContext.Provider value={provider}>
      <App />
    </DreamProviderContext.Provider>
  </StrictMode>,
);
