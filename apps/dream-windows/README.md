# Dream Windows GUI Alpha

This is the first Tauri 2 desktop shell for the Dream local workstation. It currently runs on a typed `MockDreamProvider`; backend wiring remains behind the same provider contract.

```powershell
$env:npm_config_cache = 'E:\Dream\cache\npm'
npm install
npm run test:run
npm run build
npm run tauri:build
```

All fixture paths, exports, and verification targets are intentionally rooted at `E:\Dream`. The shell includes Generate, Models, History, Lab, Microscope, and Settings routes, with the mock data label kept visible in the hardware status bar.
