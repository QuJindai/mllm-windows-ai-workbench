# Dream Windows Browser Workstation

The product GUI is the localhost browser workstation at `http://127.0.0.1:8866`. It is served by FastAPI and uses `DreamHttpProvider` in production. A desktop/Tauri executable is not part of the supported delivery path.

```powershell
$env:npm_config_cache = 'E:\Dream\cache\npm'
npm install
npm run test:run
npm run build

# from the repository root, in a PowerShell window
.\scripts\run_dream_web.ps1 -OpenBrowser
```

Use `-Build` to rebuild the browser assets before starting the server. The server binds to localhost only and invokes the native CUDA generation engine behind the HTTP API; generated PNGs, metadata, jobs, and logs stay under `E:\Dream`.

Normal `off`/`basic` generations reuse a localhost-only `sd-server` worker on port `12444`; H6/H7 capture stays on the native CLI path so latent evidence is preserved. The balanced default is 768×768, 20 steps, CFG 4, DPM++ 2M SDE, and Karras. Set `DREAM_SDCPP_SERVER_URL` only to another explicit localhost URL if the default port must change.

The browser shell includes Generate, Identity, Models, History, Lab, Microscope, and Settings routes. Native facts are marked observed, derived metrics are marked derived, and unsupported latent/attention/research features remain explicitly unavailable rather than being shown as mock results.

See the [2026-10-29 creative upgrade guide and acceptance record](../../docs/dream-windows/CREATIVE_UPGRADE_20261029.md) for independent refinement versions, explicit scene framing/recipes, real controlled fusion images and microscope comparisons. It separates local acceptance from pending main-release/CI and preserves the quality, composition, performance and device-parity limitations.
