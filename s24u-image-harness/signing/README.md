# S24U Image Harness test signing identity

**TEST-ONLY / PUBLIC LAB KEY — DO NOT USE FOR PRODUCTION OR PUBLIC APP DISTRIBUTION.**

H1 was built with an ephemeral GitHub-hosted runner debug key. Android therefore cannot install a newly built H2 APK over H1 unless the signing key is identical, and that H1 private key no longer exists. The H1→H2 transition must use the supplied `S24U_H1_MODEL_BACKUP.sh` and `S24U_H2_MODEL_RESTORE.sh` once.

From H2 onward this project deliberately uses one fixed public laboratory signing identity. Its sole purpose is to make sideloaded H2/H3/... test APKs install as normal in-place updates so Android preserves the package private data, including `files/models`. The private key is public by design for reproducible lab builds. Consequently, **anyone can sign an APK with this identity**. Do not treat an APK signed by this certificate as authenticated merely because Android accepts it as an update.

For a production or externally distributed fork, replace this identity with a private keystore stored outside Git and in CI secrets, then perform a controlled one-time migration.

Certificate SHA-256 fingerprint:

`B6:07:48:D6:46:1E:F1:F5:E2:68:14:62:F0:8E:EB:CA:28:7B:56:B7:8B:FA:FC:80:14:99:CC:2B:A4:61:E0:05`

Files:
- `s24u-test-signing-key.pem` — PUBLIC TEST-ONLY private key.
- `s24u-test-signing-cert.pem` — matching self-signed certificate.
