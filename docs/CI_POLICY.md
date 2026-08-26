# CI policy

- Standard GitHub-hosted runners only.
- No OpenAI, Codex or Copilot API calls.
- No larger runners.
- No Actions artifact/cache uploads in the default validation workflow.
- Windows tests are the release gate before physical-machine acceptance.
