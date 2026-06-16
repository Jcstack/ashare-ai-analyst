"""Prompt management API endpoints.

Per PRD v2.5 FR-PM001~PM005.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.prediction.prompt_manager import PromptManager
from src.prediction.prompt_tester import PromptTester
from src.web.dependencies import get_prompt_manager, get_prompt_tester
from src.utils.logger import get_logger

logger = get_logger("web.routes.prompts")

router = APIRouter(tags=["prompts"])


class CreatePromptRequest(BaseModel):
    id: str | None = None
    name: str
    category: str = "custom"
    description: str = ""
    system_template: str = ""
    user_template: str = ""
    variables: list[str] = []
    tags: list[str] = []


class UpdatePromptRequest(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    system_template: str | None = None
    user_template: str | None = None
    variables: list[str] | None = None
    tags: list[str] | None = None


class TestPromptRequest(BaseModel):
    variables: dict[str, str] = {}
    max_tokens: int = 2048
    temperature: float = 0.3


class OptimizePromptRequest(BaseModel):
    test_output: str | None = None


@router.get("")
async def list_prompts(
    manager: PromptManager = Depends(get_prompt_manager),
) -> list[dict[str, Any]]:
    """List all prompt templates."""
    return manager.list_prompts()


@router.get("/{prompt_id}")
async def get_prompt(
    prompt_id: str,
    manager: PromptManager = Depends(get_prompt_manager),
) -> dict[str, Any]:
    """Get a prompt template by ID, including version history."""
    result = manager.get_prompt(prompt_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' not found")
    return result


@router.post("")
async def create_prompt(
    req: CreatePromptRequest,
    manager: PromptManager = Depends(get_prompt_manager),
) -> dict[str, Any]:
    """Create a new prompt template."""
    try:
        return manager.create_prompt(req.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.put("/{prompt_id}")
async def update_prompt(
    prompt_id: str,
    req: UpdatePromptRequest,
    manager: PromptManager = Depends(get_prompt_manager),
) -> dict[str, Any]:
    """Update an existing prompt template (auto-versions)."""
    result = manager.update_prompt(prompt_id, req.model_dump(exclude_none=True))
    if result is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' not found")
    return result


@router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: str,
    manager: PromptManager = Depends(get_prompt_manager),
) -> dict[str, str]:
    """Delete a prompt template."""
    if not manager.delete_prompt(prompt_id):
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_id}' not found")
    return {"status": "deleted", "id": prompt_id}


@router.post("/{prompt_id}/test")
async def test_prompt(
    prompt_id: str,
    req: TestPromptRequest,
    tester: PromptTester = Depends(get_prompt_tester),
) -> dict[str, Any]:
    """Execute a prompt template with test variables."""
    result = tester.test_prompt(
        prompt_id=prompt_id,
        test_variables=req.variables,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
    )
    if result.get("status") == "error" and "not found" in result.get("message", ""):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/{prompt_id}/optimize")
async def optimize_prompt(
    prompt_id: str,
    req: OptimizePromptRequest,
    tester: PromptTester = Depends(get_prompt_tester),
) -> dict[str, Any]:
    """Get AI-assisted optimization suggestions for a prompt."""
    result = tester.optimize_prompt(
        prompt_id=prompt_id,
        test_output=req.test_output,
    )
    if result.get("status") == "error" and "not found" in result.get("message", ""):
        raise HTTPException(status_code=404, detail=result["message"])
    return result
