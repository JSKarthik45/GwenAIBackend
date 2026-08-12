    
import json
import os
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


# Simple base output for the generated app; agents should write relative paths under this folder.
BASE_OUTPUT = Path(__file__).resolve().parents[4] / "GeneratedMVP" / "MyApp"
BASE_OUTPUT.mkdir(parents=True, exist_ok=True)


class FileWriteInput(BaseModel):
    path: str = Field(..., description="Relative or absolute path to write file.")
    content: str = Field(..., description="File contents")


class FileReadInput(BaseModel):
    path: str = Field(..., description="Relative or absolute path to read file.")


def _resolve_target(path: str) -> Path:
    candidate = Path(path)
    target = candidate if candidate.is_absolute() else BASE_OUTPUT / candidate
    target = target.resolve()
    try:
        target.relative_to(BASE_OUTPUT)
    except Exception:
        # Allow absolute paths but do not allow traversal outside BASE_OUTPUT for relative paths
        if not candidate.is_absolute():
            raise ValueError("Path outside base output")
    return target


class FileWriterTool(BaseTool):
    name: str = "file_writer"
    description: str = "Write a file under the GeneratedMVP/MyApp output folder."
    args_schema: Type[BaseModel] = FileWriteInput

    def _run(self, path: str, content: str) -> str:
        try:
            target = _resolve_target(path)
        except ValueError as exc:
            return f"ERROR: {exc}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        rel = target.relative_to(BASE_OUTPUT)
        return f"SUCCESS: {rel} written ({len(content)} bytes)"


class FileReaderTool(BaseTool):
    name: str = "file_reader"
    description: str = "Read a file from the GeneratedMVP/MyApp output folder."
    args_schema: Type[BaseModel] = FileReadInput

    def _run(self, path: str) -> str:
        try:
            target = _resolve_target(path)
        except ValueError as exc:
            return f"ERROR: {exc}"
        if not target.exists() or not target.is_file():
            return f"ERROR: {path} does not exist"
        return target.read_text(encoding="utf-8")

