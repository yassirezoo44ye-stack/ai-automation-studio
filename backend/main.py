from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from routers.auth import (
    hash_password,
    verify_password,
    create_access_token,
    decode_token,
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

users = {}
projects = {}
runs = {}


class Register(BaseModel):
    email: str
    password: str


class Login(BaseModel):
    email: str
    password: str


class ProjectCreate(BaseModel):
    user_id: str
    name: str


class AgentRunRequest(BaseModel):
    project_id: str
    prompt: str


@app.get("/")
def home():
    return {
        "name": "AI Automation Studio",
        "status": "running"
    }


@app.post("/register")
def register(data: Register):
    if data.email in users:
        raise HTTPException(status_code=400, detail="User exists")

    users[data.email] = {
        "email": data.email,
        "password": hash_password(data.password)
    }

    return {"message": "User created"}


@app.post("/login")
def login(data: Login):
    user = users.get(data.email)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(data.password, user["password"]):
        raise HTTPException(status_code=401, detail="Wrong password")

    token = create_access_token({"sub": data.email})

    return {"access_token": token}


@app.get("/projects")
def get_projects():
    return list(projects.values())


@app.post("/projects")
def create_project(data: ProjectCreate):
    project_id = str(uuid4())

    projects[project_id] = {
        "id": project_id,
        "user_id": data.user_id,
        "name": data.name
    }

    return projects[project_id]


@app.post("/run")
def run_agent(data: AgentRunRequest):
    run_id = str(uuid4())

    result = {
        "summary": f"AI processed: {data.prompt}"
    }

    runs[run_id] = {
        "id": run_id,
        "project_id": data.project_id,
        "prompt": data.prompt,
        "result": result
    }

    return runs[run_id]


@app.get("/runs")
def get_runs():
    return list(runs.values())