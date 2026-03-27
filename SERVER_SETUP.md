# SBS EnergyLink — Server Setup & Claude Code Instructions

## What You Need

- Ubuntu 22.04 LTS test server (VM, bare metal, or cloud instance)
- Python 3.10 or higher
- Git
- Internet access for pip installs
- Claude Code installed (`npm install -g @anthropic-ai/claude-code`)

---

## Step 1 — Get the Code onto Your Server

```bash
# Option A: Clone from wherever you put it (GitHub, GitLab, etc.)
git clone https://github.com/your-org/sbs-energylink.git
cd sbs-energylink

# Option B: Copy the zip from this conversation
# Unzip sbs-energylink-vscode.zip and copy to server via scp or SFTP
scp sbs-energylink-vscode.zip user@your-server:/home/user/
ssh user@your-server
unzip sbs-energylink-vscode.zip
cd sbs-energylink
```

---

## Step 2 — Install Python Dependencies

```bash
# On Ubuntu with system Python
pip install -r requirements.txt --break-system-packages

# Or use a virtual environment (cleaner)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Verify installs
python3 -c "import pymodbus; print('pymodbus OK')"
python3 -c "import BAC0; print('BAC0 OK')"
python3 -c "import flask; print('Flask OK')"
```

---

## Step 3 — Run in Simulation Mode (No Hardware Needed)

This starts all three services — Modbus poller (simulated), BACnet server,
and the setup wizard web UI.

```bash
cd sbs-energylink
python3 src/main.py --sim --loglevel DEBUG
```

You should see output like:
```
2026-03-27 [INFO] main: SBS EnergyLink starting — Site: Unconfigured
2026-03-27 [INFO] *** SIMULATION MODE — no real Modbus connection ***
2026-03-27 [INFO] bacnet-server: Starting BACnet/IP server — Device ID: 9001
2026-03-27 [INFO] web-ui: Setup wizard on http://10.10.10.1:80
2026-03-27 [INFO] All services running. Press Ctrl+C to stop.
```

**Note on web UI port:** The wizard binds to port 80 by default which requires
root on Linux. Either:

```bash
# Option A: Run as root (dev only)
sudo python3 src/main.py --sim --loglevel DEBUG

# Option B: Change the port in config.template.yaml
webui_port: 8080
# Then access at http://localhost:8080

# Option C: Use authbind
sudo apt install authbind
sudo touch /etc/authbind/byport/80
sudo chmod 777 /etc/authbind/byport/80
authbind python3 src/main.py --sim
```

---

## Step 4 — Open Claude Code in the Project

```bash
cd sbs-energylink

# Start Claude Code
claude

# Claude Code will read CLAUDE.md automatically and understand the project
```

Claude Code reads `CLAUDE.md` first and understands:
- What the project does
- What's already built
- What still needs building (the TODO list)
- All the design decisions and constraints

---

## Step 5 — Things to Ask Claude Code to Build

The `CLAUDE.md` TODO list covers the main remaining work. Good starting points:

```
# Ask Claude Code to run the tests first
> run the test suite and fix any failures

# Then build the remaining pieces
> update the wizard templates to use the new 4-step flow

> add the /api/jace_reachable endpoint and test it

> write a build_image.sh script that creates a deployable SD card image

> add a watchdog that restarts the poller if data goes stale for 5 minutes

> validate all 23 BACnet objects are being created correctly in sim mode
```

---

## Step 6 — Run the Test Suite

```bash
cd sbs-energylink

# Install pytest if not already installed
pip install pytest --break-system-packages

# Run all tests
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_energylink.py -v

# Run with output on failure
python3 -m pytest tests/ -v -s
```

Expected output on a clean install:
```
tests/test_energylink.py::TestDataStore::test_initial_state_is_stale PASSED
tests/test_energylink.py::TestDataStore::test_update_clears_stale PASSED
tests/test_energylink.py::TestModbusParsing::test_int16_signed_positive PASSED
...
```

---

## Step 7 — Test the Setup Wizard

With the app running in sim mode (`python3 src/main.py --sim`):

```bash
# In another terminal — test the API endpoints
curl http://localhost:8080/api/status
curl http://localhost:8080/api/jace_reachable
curl http://localhost:8080/api/test_modbus
```

Or open a browser to `http://localhost:8080` (or port 80 if running as root)
and walk through all 4 wizard steps.

The Step 4 handoff page should show:
- EPMS connection status
- BACnet server running
- JACE reachability check
- Direct link to http://10.10.10.2 (JACE web UI)
- The 23 BACnet point list
- Clear instructions for the BAS integrator

---

## Common Issues

**BAC0 port conflict:**
```
Error: [Errno 98] Address already in use (port 47808)
```
Something else is using BACnet port. Kill it:
```bash
sudo lsof -i :47808
sudo kill -9 <PID>
```

**pymodbus import error:**
```bash
pip install pymodbus==3.6.4 --break-system-packages --force-reinstall
```

**Flask template not found:**
Make sure you run from the project root, not from inside `src/`:
```bash
cd sbs-energylink   # ← project root
python3 src/main.py --sim
```

**Permission denied port 80:**
Use port 8080 in config (see Step 3 options above).

---

## Project File Reference

```
sbs-energylink/
├── CLAUDE.md              ← Claude Code reads this first (project guide)
├── SERVER_SETUP.md        ← This file
├── README.md              ← Human overview
├── requirements.txt       ← pip dependencies
│
├── src/
│   ├── main.py            ← Start here — entry point
│   ├── poller.py          ← Modbus TCP reader
│   ├── bacnet_server.py   ← BACnet/IP server
│   ├── data_store.py      ← Shared state between threads
│   └── web_ui.py          ← Flask setup wizard (4 steps)
│
├── config/
│   └── config.template.yaml  ← Default config, edit for dev
│
├── templates/
│   ├── step1.html         ← Site info
│   ├── step2.html         ← EPMS/Modbus connection
│   ├── step3.html         ← BACnet Device ID
│   └── step4.html         ← Integrator handoff page
│
├── tests/
│   └── test_energylink.py ← pytest test suite
│
└── docs/
    └── integrator-setup-sheet.md  ← Handoff doc for BAS integrators
```

---

## What Claude Code Can Do In This Project

Claude Code has full read/write access to the project files. Good tasks for it:

- **Fix failing tests** — `> run pytest and fix any failures`
- **Add features** — `> add a factory reset endpoint that clears config.yaml`
- **Improve the wizard** — `> make step 4 auto-refresh the JACE reachability check every 10 seconds`
- **Generate docs** — `> generate a PDF version of the integrator setup sheet`
- **Deployment** — `> write a Dockerfile so this runs in a container`
- **Hardware config** — `> update network-config.yaml to support static IP on eth0 as an option in the wizard`
- **Testing** — `> add integration tests that mock the full Modbus → BACnet flow`

The `CLAUDE.md` file is the source of truth. Claude Code reads it at the
start of every session so it always knows the current project state.
