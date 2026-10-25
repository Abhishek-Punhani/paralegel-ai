# NyayaLens

NyayaLens is an AI paralegal for Indian motor accident matters. Clients complete a focused voice interview through a private consultation link. Advocates review the incident account, chronology, separate client and victim profiles, documents, and unresolved questions, then accept the matter for deeper research and analysis.

Speech recognition and synthesis run through **Sarvam AI** on the server. FastAPI and LangGraph manage the interview and analysis, Gemini powers extraction and legal analysis, and Indian Kanoon supplies live authorities. Next.js provides the client call experience and authenticated advocate workspace.

## Demo workflow

1. Open the website and enter the advocate workspace. Register an advocate account or sign in to an existing account.
2. Choose **Add New Client**, enter the actual client's details, and generate a consultation link.
3. Open the link in another browser tab or on the client's phone. Allow microphone access and agree to the interview.
4. Speak naturally in Hindi, Hinglish, or English. Use the call controls to submit voice responses. Nyaya asks focused follow-ups, including the exact FIR sections or charges. Upload requested documents through the overlay when available.
5. End the call and return to the advocate workspace. Open the client and review the four intake sections: incident narrative, chronology, client profile, and victim profile.
6. Choose **Accept Case & Run Analysis**. The progress panel reports actual pipeline events while research runs. Review opposition arguments, precedents, investigation targets, law sections, client arguments, and the evidence-based assessment.
7. Ask follow-up strategy questions in the packet chat. Check cited authorities and unresolved evidence before relying on an argument.

There are no seeded clients or simulated pipeline events. The interview, speech, document extraction, research, and chat need configured provider credentials and internet access. Provider failures appear as recoverable errors in the interface.

## Run locally

Prerequisites: Python 3.12, Node.js 20, and provider API keys.

```bash
cp backend/.env.example backend/.env
cp web/.env.example web/.env.local
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

Set `SARVAM_API_KEY`, `GOOGLE_API_KEY`, and `INDIAN_KANOON_TOKEN` in `backend/.env`. Choose available Gemini models using the model environment variables. Set the same strong `JWT_SECRET` in `backend/.env` and `web/.env.local`. Set `DATABASE_URL=file:./dev.db` in the web environment.

Start the API from the backend directory:

```bash
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Start the web application in another terminal:

```bash
cd web
npm ci
DATABASE_URL=file:./dev.db npx prisma generate
python3 -c "import sqlite3; db = sqlite3.connect('prisma/dev.db'); db.execute('PRAGMA user_version=0'); db.close()"
DATABASE_URL=file:./dev.db npx prisma db push
npm run dev
```

Open `http://localhost:3000`. Next.js forwards the backend API paths locally. Browser microphone access works on localhost; a remote domain requires HTTPS. Keep provider secrets out of `NEXT_PUBLIC_*` variables.

## Production

The submission deployment target is `https://nyayalens.abhi07.xyz`. The repository includes an isolated GCP Compute Engine + Cloudflare Terraform module, production containers, persistent SQLite volumes, and a Caddy HTTPS/SSE/WebSocket gateway. See [deployment instructions](deploy/README.md) for provisioning, uploads, health checks, logs, and rollback.

## Repository

- `backend/app/voice.py` and `backend/app/services/sarvam.py`: server-side speech and voice turns.
- `backend/app/intake_engine`: deterministic interview progression and question coverage.
- `backend/app/agents` and `backend/app/graphs`: intake extraction, research, opposition analysis, arguments, and packet generation.
- `web/src/components/client`: consultation call interface and document modal.
- `web/src/components/lawyer`: intake review, streaming progress, final packet, and follow-up chat.
- `web/src/app/api`: advocate authentication and client session management.
- `deploy`: gateway, infrastructure, and publication tooling.

The current deployment uses one backend process; active audio turns and live subscriptions are process-local. Persisted checkpoints and account data survive container restarts. A larger deployment should replace process-local task/subscription coordination with a shared worker and event service.
