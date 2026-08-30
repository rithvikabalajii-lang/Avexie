# Sovereign AI demo

This deployment keeps Ollama and Judge0 on Docker networks declared
`internal: true`. The application's host-visible bridge has IP masquerading
disabled and a stateful output firewall allows only loopback, established
host sessions and directly connected service subnets. New public connections
are dropped while the published local port remains usable.
Cloud model providers and telemetry are disabled. Download model weights before
switching to the isolated stack.

## One-time setup

```bash
docker compose pull
docker compose up -d ollama
docker exec ollama ollama pull qwen2.5:3b
docker exec ollama ollama pull qwen2.5-coder:3b
docker exec ollama ollama pull moondream:latest
docker compose build avexie
docker compose up -d
```

Open <http://localhost:3000>. The three small models are suitable for a
mid-range workstation; substitute larger local models when GPU memory permits.

## Judge walkthrough

1. Open **Workspace → Models**. The routed Ollama inventory shows inferred
   capability, family, size, quantization and routing tags. Leave chat on
   **Auto route**. Ask a general question and a coding question; each response
   displays a `Routed to …` process step. **Manual model** is the explicit
   override.
2. Open **Workspace → Knowledge**, create a knowledge base and upload a scanned
   inspection report. Local RapidOCR extracts image/PDF text and Chroma stores
   the chunks. Ask the agent to identify findings and draft an approval note,
   then tell it to use `generate_word_document`. The response shows the local
   Chroma grounding step and provides a local `.docx` download.
3. Open the full-page **IDE**, choose **Import folder**, and ask the IDE agent
   for a change. It talks directly to Ollama using the complete imported
   workspace. Review red removals and green additions, then **Approve**, or turn
   on **Auto-apply edits**. Click **Run** to execute in Judge0. Judge0 enforces
   CPU, memory, process, file and wall-time limits with networking disabled.
4. Attach an inspection image in chat and ask for visible defects. Auto routing
   selects the local vision model. In a channel, `@Agent` invokes the same
   router; individual model mentions are intentionally unavailable.
5. Send follow-up questions in the same chat. The backend reconstructs the
   complete ancestor thread from stored messages before routing, rather than
   treating each turn as a new conversation.

## Proving zero external calls

The IDE header and backend sovereignty endpoint report `0 external calls`.
Run the independent network test during the demo:

```bash
./scripts/verify-sovereignty.sh
```

It verifies both Docker networks are internal, confirms local Ollama access,
proves a public HTTPS request fails, and checks the cloud-provider/Chroma
runtime policy. Route, Chroma-grounding and tool-authorization audit events are
also visible in application process steps and container logs.
