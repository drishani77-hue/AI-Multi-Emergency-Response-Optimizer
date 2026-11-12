# ResQTech — AI-Assisted Multi-Emergency Response & Resource Optimizer

ResQTech is a multi-emergency response and resource optimization system designed to assist in handling simultaneous emergencies. It combines C-based data structures, shortest-path algorithms, a Python backend, and a web interface to support emergency prioritization, resource selection, and route optimization.

## Current Status

**In Development**

The current implementation includes emergency reporting, emergency triage, organization and resource registration, a C-based road-network engine, and automated tests.

## Core Technologies

- **C:** Graph representation, adjacency lists, Dijkstra's shortest-path algorithm, and resource ranking.
- **Python:** Backend integration, emergency triage, and application logic.
- **Flask:** REST API.
- **SQLite:** Data persistence.
- **React:** Frontend.
- **OpenStreetMap:** Road-network data.
- **Leaflet:** Map visualization.

## Project Structure

```text
ResQTech/
├── backend/
│   ├── app.py
│   ├── emergency_triage.py
│   └── road_engine.py
├── c_engine/
│   ├── src/
│   │   ├── graph.c
│   │   ├── dijkstra.c
│   │   ├── ranking.c
│   │   ├── bridge.c
│   │   └── ...
│   └── build/
├── data/
│   ├── osm/
│   ├── road_nodes.csv
│   └── road_edges.csv
├── database/
├── docs/
├── frontend/
├── tests/
├── requirements.txt
└── README.md
```

## C Road Engine Setup (Windows)

The road engine is implemented in C and accessed from Python through a shared library.

### Prerequisites

- GCC compiler (MinGW-w64 or MSYS2)
- Python 3.12
- Git

### Build the shared library

From the project root, run the following in PowerShell:

```powershell
New-Item -ItemType Directory -Force c_engine\build

gcc -std=c11 -O2 -Wall -Wextra -Werror -shared `
    -o c_engine/build/resqtech_engine.dll `
    c_engine/src/graph.c `
    c_engine/src/dijkstra.c `
    c_engine/src/ranking.c `
    c_engine/src/bridge.c
```

The generated DLL is a local build artifact and is not committed to Git. Build it before running the application.

## Road-Network Data

ResQTech uses road-network data derived from OpenStreetMap.

OpenStreetMap contributors are credited in `data/osm/ATTRIBUTION.txt`. The data is subject to the Open Database License (ODbL).

## Running Tests

Activate the project's virtual environment and run:

```powershell
python -m pytest -q
```

## Team

Developed as a team project for the Data Structures using C course at Graphic Era Deemed to be University.
