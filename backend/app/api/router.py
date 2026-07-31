from fastapi import APIRouter

from app.api import blueprints, documents, jobs, libraries, model_profiles, papers, practice

api_router = APIRouter()
api_router.include_router(libraries.router)
api_router.include_router(documents.router)
api_router.include_router(model_profiles.router)
api_router.include_router(jobs.router)
api_router.include_router(blueprints.router)
api_router.include_router(papers.router)
api_router.include_router(practice.router)

