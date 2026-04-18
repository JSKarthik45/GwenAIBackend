import json
import os
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# Base directory for all generated files; prevents cluttering the repo root
# This is set dynamically by main.py based on user prompt
BASE_OUTPUT = Path("D:/GwenAIBackend/GeneratedMVP/MyApp").resolve()
DEPENDENCY_REGISTRY = BASE_OUTPUT / ".agent_dependency_registry.json"
BOOTSTRAP_MARKER = BASE_OUTPUT / ".expo_bootstrapped"

_DEPENDENCY_RENAMES = {
    "@react-native-community/async-storage": "@react-native-async-storage/async-storage",
}

def set_base_output_path(app_folder: str) -> None:
    """Configure BASE_OUTPUT, DEPENDENCY_REGISTRY, and BOOTSTRAP_MARKER for a specific app folder.
    
    Must be called BEFORE tools are instantiated.
    
    Args:
        app_folder: Folder name under GeneratedMVP/ (e.g., "todo_app", "note_app")
    """
    global BASE_OUTPUT, DEPENDENCY_REGISTRY, BOOTSTRAP_MARKER
    BASE_OUTPUT = Path(f"D:/GwenAIBackend/GeneratedMVP/{app_folder}").resolve()
    BASE_OUTPUT.mkdir(parents=True, exist_ok=True)
    DEPENDENCY_REGISTRY = BASE_OUTPUT / ".agent_dependency_registry.json"
    BOOTSTRAP_MARKER = BASE_OUTPUT / ".expo_bootstrapped"

class FileWriteInput(BaseModel):
    """Input schema for writing a file to disk."""

    path: str = Field(
        ...,
        description="File path to write. Prefer relative paths like src/index.js; absolute paths under the generated app root are also accepted.",
    )
    content: str = Field(..., description="Full file contents to write")

class FileReadInput(BaseModel):
    """Input schema for reading a file from disk."""

    path: str = Field(..., description="Relative file path to read (e.g., app/index.tsx)")

class TrackDependencyInput(BaseModel):
    """Input schema for recording dependency additions during generation."""

    library: str = Field(..., description="Dependency name, e.g. axios")
    version: str | None = Field(
        default=None,
        description="Deprecated. Ignored.",
    )

def _resolve_target(path: str) -> Path:
    """Resolve target path under the sandbox root and block traversal."""
    candidate = Path(path)
    target = candidate if candidate.is_absolute() else BASE_OUTPUT / candidate
    target = target.resolve()

    # Use Path.relative_to to avoid false negatives from Windows path case differences.
    try:
        target.relative_to(BASE_OUTPUT)
    except ValueError as exc:
        raise ValueError(f"Security violation. {path} is outside the sandbox.") from exc

    return target

def _read_dependency_registry() -> dict[str, list[str]]:
    if not DEPENDENCY_REGISTRY.exists():
        return {"dependencies": [], "devDependencies": []}

    raw = DEPENDENCY_REGISTRY.read_text(encoding="utf-8").strip()
    payload: dict | None = None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Recover from accidentally concatenated JSON by decoding only the first object.
        try:
            decoder = json.JSONDecoder()
            parsed, _ = decoder.raw_decode(raw)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = None

    if payload is None:
        payload = {"dependencies": [], "devDependencies": []}

    deps = payload.get("dependencies", [])
    dev_deps = payload.get("devDependencies", [])

    # Backward compatibility: convert old dict format {name: version} into list format [name]
    if isinstance(deps, dict):
        deps = list(deps.keys())
    if isinstance(dev_deps, dict):
        dev_deps = list(dev_deps.keys())

    normalized_deps = {
        _DEPENDENCY_RENAMES.get(str(item).strip(), str(item).strip())
        for item in deps
        if str(item).strip()
    }
    normalized_dev_deps = {
        _DEPENDENCY_RENAMES.get(str(item).strip(), str(item).strip())
        for item in dev_deps
        if str(item).strip()
    }

    normalized = {
        "dependencies": sorted(normalized_deps),
        "devDependencies": sorted(normalized_dev_deps),
    }

    # Self-heal malformed or legacy formats to keep subsequent runs stable.
    _write_dependency_registry(normalized)
    return normalized

def _write_dependency_registry(payload: dict[str, list[str]]) -> None:
    DEPENDENCY_REGISTRY.write_text(json.dumps(payload, indent=2), encoding="utf-8")

def _is_bootstrapped() -> bool:
    return BOOTSTRAP_MARKER.exists()

class FileWriterTool(BaseTool):
    name: str = "file_writer"
    description: str = (
        "MANDATORY: Use this tool to save EVERY file. Provide a RELATIVE path inside the current GeneratedMVP app folder "
        "(with extension) and full file content. Never show code in chat; always write via this tool. Creates parent "
        "directories; overwrites existing files; prevents escaping the base directory."
    )
    args_schema: Type[BaseModel] = FileWriteInput

    def _run(self, path: str, content: str) -> str:
        if not _is_bootstrapped():
            return (
                "ERROR: Expo template bootstrap has not completed. "
                "Run expo_bootstrap successfully before writing any files."
            )

        # Resolve to the enforced base directory to prevent path traversal; handles forward/back slashes
        try:
            target = _resolve_target(path)
        except ValueError as exc:
            return f"ERROR: {exc}"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        try:
            relative_target = target.relative_to(BASE_OUTPUT)
        except ValueError:
            relative_target = target

        return (
            f"SUCCESS: {relative_target} written ({len(content)} bytes). "
            f"Next: continue writing remaining files from the architecture plan."
        )

class FileReaderTool(BaseTool):
    name: str = "file_reader"
    description: str = (
        "Read an existing file from the current GeneratedMVP app folder. Use this before changing template-generated files "
        "so edits are based on current content."
    )
    args_schema: Type[BaseModel] = FileReadInput

    def _run(self, path: str) -> str:
        try:
            target = _resolve_target(path)
        except ValueError as exc:
            return f"ERROR: {exc}"

        if not target.exists() or not target.is_file():
            return f"ERROR: {path} does not exist."

        content = target.read_text(encoding="utf-8")
        return f"SUCCESS: {path}\n{content}"

class TrackDependencyTool(BaseTool):
    name: str = "track_dependency"
    description: str = (
        "Record each added library name while generating files. Use this every time you introduce a new "
        "import that is not in the template dependencies."
    )
    args_schema: Type[BaseModel] = TrackDependencyInput

    def _run(
        self,
        library: str,
        version: str | None = None,
        dependency_type: str | None = None,
    ) -> str:
        # dependency_type is optional for backward compatibility; default to dependencies
        normalized_type = (dependency_type or "dependencies").strip()
        if normalized_type not in {"dependencies", "devDependencies"}:
            normalized_type = "dependencies"

        lib = library.strip()
        if not lib:
            return "ERROR: library is required."

        lib = _DEPENDENCY_RENAMES.get(lib, lib)

        registry = _read_dependency_registry()
        current = set(registry.get(normalized_type, []))
        current.add(lib)
        registry[normalized_type] = sorted(current)
        _write_dependency_registry(registry)
        return f"SUCCESS: Tracked {lib} in {normalized_type}."

def remove_default_src_files() -> None:
    """Remove only legacy files that conflict with current template workflow.

    IMPORTANT: Preserve TemplateMVP shell files such as root App.js and index.js.
    """
    default_files = [
        BASE_OUTPUT / "index.ts",
    ]
    
    for file in default_files:
        try:
            if file.exists():
                file.unlink()
        except Exception:
            pass
