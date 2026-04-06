from typing import Any
from fastapi import APIRouter, HTTPException
from sentinelflow.api.schemas import AgentCreateRequest, DeleteRequest

router = APIRouter()

# Global dependencies to be injected at startup
_agent_root = None
_system_primary_agent_name = None
_list_agent_defs = None
_read_agent_yaml = None
_normalize_agent_role = None
_assert_unique_plugin_name = None
_assert_single_enabled_primary = None
_slugify = None
_build_agent_yaml = None
_mirror_project_file = None
_remove_project_path = None
_reload_agent_service = None

def init_agent_router(kwargs):
    global _agent_root, _system_primary_agent_name, _list_agent_defs, _read_agent_yaml, _normalize_agent_role
    global _assert_unique_plugin_name, _assert_single_enabled_primary, _slugify, _build_agent_yaml
    global _mirror_project_file, _remove_project_path, _reload_agent_service
    _agent_root = kwargs.get("agent_root")
    _system_primary_agent_name = kwargs.get("system_primary_name")
    _list_agent_defs = kwargs.get("list_agent_defs")
    _read_agent_yaml = kwargs.get("read_agent_yaml")
    _normalize_agent_role = kwargs.get("normalize_agent_role")
    _assert_unique_plugin_name = kwargs.get("assert_unique_plugin_name")
    _assert_single_enabled_primary = kwargs.get("assert_single_enabled_primary")
    _slugify = kwargs.get("slugify")
    _build_agent_yaml = kwargs.get("build_agent_yaml")
    _mirror_project_file = kwargs.get("mirror_project_file")
    _remove_project_path = kwargs.get("remove_project_path")
    _reload_agent_service = kwargs.get("reload_agent_service")

@router.get("")
def list_agents() -> list[dict[str, Any]]:
    return _list_agent_defs()

@router.get("/{name}")
def get_agent(name: str) -> dict[str, Any]:
    try:
        return _read_agent_yaml(name)
    except Exception:
        raise HTTPException(status_code=404, detail="找不到指定的 Agent。")

@router.post("")
def create_agent(req: AgentCreateRequest) -> dict[str, str]:
    if req.name.strip().lower() == _system_primary_agent_name.lower():
        raise HTTPException(status_code=400, detail="不能创建名为系统默认主 Agent 的配置。")
    req.role = _normalize_agent_role(req)
    slug = _slugify(req.name)
    _assert_unique_plugin_name(req.name, slug, "agent")
    _assert_single_enabled_primary(req)
    yaml_content = _build_agent_yaml(req)
    # Simple relative path mimicking what was done in app.py
    # Since agent_root is Path, it's relative to PROJECT_ROOT in the monolith
    relative_dir = _agent_root.relative_to(_agent_root.parents[4]) / slug
    _mirror_project_file(relative_dir / "agent.yaml", yaml_content)
    if req.prompt:
        _mirror_project_file(relative_dir / "prompt.md", req.prompt)
    if _reload_agent_service:
        _reload_agent_service()
    return {"message": f'Agent "{req.name}" 创建成功 ({slug})。', "name": slug}

@router.post("/{name}/save")
def save_agent(name: str, req: AgentCreateRequest) -> dict[str, str]:
    if name.strip().lower() == _system_primary_agent_name.lower():
        if req.name != _system_primary_agent_name:
            raise HTTPException(status_code=400, detail="不能修改系统主 Agent 的名称。")
        slug = name.strip().lower()
    else:
        if req.name.strip().lower() == _system_primary_agent_name.lower():
            raise HTTPException(status_code=400, detail="不能将非系统 Agent 命名为系统主 Agent。")
        slug = name.strip().lower()
        _assert_unique_plugin_name(req.name, slug, "agent", current_name=slug)
    
    req.role = _normalize_agent_role(req)
    _assert_single_enabled_primary(req, current_name=slug)
    yaml_content = _build_agent_yaml(req)
    relative_dir = _agent_root.relative_to(_agent_root.parents[4]) / slug
    _mirror_project_file(relative_dir / "agent.yaml", yaml_content)
    if req.prompt:
        _mirror_project_file(relative_dir / "prompt.md", req.prompt)
    if _reload_agent_service:
        _reload_agent_service()
    return {"message": f'Agent "{req.name}" 保存成功。', "name": slug}

@router.post("/{name}/delete")
def delete_agent(name: str, req: DeleteRequest) -> dict[str, str]:
    target_name = (req.name or name).strip()
    if target_name.lower() == _system_primary_agent_name.lower():
        raise HTTPException(status_code=400, detail="不能删除系统默认的主 Agent。")
    if not target_name:
        raise HTTPException(status_code=400, detail="名称不能为空。")
    relative_dir = _agent_root.relative_to(_agent_root.parents[4]) / target_name.lower()
    _remove_project_path(relative_dir)
    if _reload_agent_service:
        _reload_agent_service()
    return {"message": f'Agent "{target_name}" 已删除。'}
