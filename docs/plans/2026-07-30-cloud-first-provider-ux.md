# MindType Cloud-first provider UX

## Outcome

A new MindType user sees one product route: MindType Cloud for generated
documents. Existing users who already configured a legacy BYOK or local LLM
provider keep that exact route after upgrade, but legacy providers are not
offered as new choices in the ordinary settings UI.

## Current technical boundary

MindType Cloud currently implements the LLM document-generation API, balance,
and licensing. It does not yet expose a verified STT upload endpoint in this
repository. Therefore this slice does not pretend that speech recognition has
already moved to Cloud: the existing transcription adapters and model download
remain compatible until a real Cloud STT contract exists.

The future corporate custom endpoint is likewise not advertised or represented
as implemented until its authentication, upload, retention, and result
contracts exist.

## Acceptance criteria

1. A brand-new config defaults to `use_mindtype_cloud=True` and
   `llm_provider="mindtype_cloud"`.
2. The ordinary provider picker contains only MindType Cloud for a new or
   already-cloud config.
3. If a loaded config explicitly selected a known legacy provider, the picker
   contains MindType Cloud plus only that selected provider, preserving the
   route without inviting new BYOK configuration.
4. Unknown legacy provider values fail closed to the MindType Cloud option
   instead of being rendered as arbitrary UI.
5. Existing API keys, model identifiers, local URLs, and transcription backend
   values continue to load and save unchanged.
6. The first-run wizard does not register or navigate to the dormant BYOK API
   key page.
7. The UI continues to disable Cloud summarization when there is no active
   license, so the new default cannot spend credits or fail unexpectedly.
8. Tests describe the product boundary, including the fact that legacy
   compatibility remains data-compatible rather than becoming a new-user
   feature.

## Non-goals

- Implementing or claiming a MindType Cloud STT endpoint.
- Deleting legacy provider adapters or stored secrets in this release.
- Adding a speculative corporate custom-endpoint form.
- Reworking credit pricing or server-side retention.
