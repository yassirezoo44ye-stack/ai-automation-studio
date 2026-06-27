# AI Automation Studio

A FastAPI + PostgreSQL application with Arabic UI for managing AI projects, agent runs, and usage logging with Row-Level Security.

## Features

- Arabic UI with RTL support
- Projects CRUD operations
- Agent runs management
- Usage logging and analytics
- Row-Level Security (RLS) for data isolation
- Docker support
- Railway deployment ready

## API Endpoints

- GET /health - Health check
- POST /api/projects - Create project
- GET /api/projects - List projects
- GET /api/projects/{id} - Get project
- PUT /api/projects/{id} - Update project
- DELETE /api/projects/{id} - Delete project
- POST /api/agent-runs - Start agent run
- GET /api/agent-runs - List agent runs
- POST /api/usage-logs - Create usage log
- GET /api/usage-logs - List usage logs

## Environment Variables

- DATABASE_URL - PostgreSQL connection string
- PORT - Application port (default: 8000)
