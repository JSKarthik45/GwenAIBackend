#!/usr/bin/env python
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure the package root (…/mycrew/src) is on sys.path when run directly
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

_REPO_ROOT = Path(__file__).resolve().parents[3]

from mycrew.crew import Mycrew
from mycrew.crew import run_debugging_agent
from mycrew.tools.custom_tool import (
    set_base_output_path,
    remove_default_src_files,
)


def _is_tool_call_payload_error(exc: Exception) -> bool:
    text = str(exc)
    return "tool_use_failed" in text and "Failed to call a function" in text


def _run_crew_with_retries(inputs: dict[str, str]):
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            return Mycrew().crew().kickoff(inputs=inputs)
        except Exception as exc:
            if _is_tool_call_payload_error(exc) and attempt < attempts:
                print(
                    f"⚠ Tool-call payload rejected by provider (attempt {attempt}/{attempts}). Retrying crew kickoff..."
                )
                continue
            raise


def _extract_task_outputs(crew_output) -> tuple[str, str, str]:
    """Extract planner, architecture, and coding outputs from CrewAI kickoff result."""
    task_outputs = getattr(crew_output, "tasks_output", None) or []
    normalized: list[str] = []

    for task_output in task_outputs:
        raw = getattr(task_output, "raw", None)
        normalized.append(str(raw if raw is not None else task_output))

    if len(normalized) >= 3:
        return normalized[0], normalized[1], normalized[2]

    fallback = getattr(crew_output, "raw", None)
    final_text = str(fallback if fallback is not None else crew_output)
    return "", "", final_text


def _apply_corrected_codebase(codebase_json: str) -> int:
    """Write corrected file map JSON into the generated app directory safely."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT

    payload = json.loads(codebase_json)
    if not isinstance(payload, dict):
        raise ValueError("Corrected codebase must be a JSON object.")

    files_written = 0
    for relative_path, content in payload.items():
        if not isinstance(relative_path, str) or not isinstance(content, str):
            raise ValueError("Corrected codebase entries must be {string: string}.")

        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError(f"Absolute path is not allowed in corrected codebase: {relative_path}")

        target = (TOOL_BASE_OUTPUT / candidate).resolve()
        try:
            target.relative_to(TOOL_BASE_OUTPUT)
        except ValueError as exc:
            raise ValueError(f"Path escapes generated app directory: {relative_path}") from exc

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        files_written += 1

    return files_written

def create_index_js() -> None:
    """Create/preserve index.js entry point that points to src/App.
    
    This is required by Expo as the main entry point. Even if agents 
    write App.js in src/, this file must exist at the root.
    """
    # Import locally to get the updated BASE_OUTPUT from custom_tool
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT
    
    index_file = TOOL_BASE_OUTPUT / "index.js"
    content = """import { registerRootComponent } from 'expo';

import App from './src/App';

// registerRootComponent calls AppRegistry.registerComponent('main', () => App);
// It also ensures that whether you load the app in Expo Go or in a native build,
// the environment is set up appropriately
registerRootComponent(App);
"""
    index_file.write_text(content, encoding="utf-8")
    print("✓ index.js entry point created (points to ./src/App)")

def update_app_json() -> None:
    """Set static app identity in app.json."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT
    
    app_json = TOOL_BASE_OUTPUT / "app.json"
    if not app_json.exists():
        print("⚠ app.json not found, skipping dynamic name update")
        return
    
    try:
        config = json.loads(app_json.read_text(encoding="utf-8"))
        config["expo"]["name"] = "MyApp"
        config["expo"]["slug"] = "myapp"
        app_json.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        print("✓ app.json updated: name='MyApp', slug='myapp'")
    except Exception as e:
        print(f"⚠ Could not update app.json: {e}")

def bootstrap_expo_directly() -> bool:
    """Bootstrap Expo template directly in code (not through agents)."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT, BOOTSTRAP_MARKER as TOOL_BOOTSTRAP_MARKER
    
    TOOL_BASE_OUTPUT.mkdir(parents=True, exist_ok=True)
    package_json = TOOL_BASE_OUTPUT / "package.json"
    
    if package_json.exists():
        TOOL_BOOTSTRAP_MARKER.write_text("ok\n", encoding="utf-8")
        print("✓ Expo template already bootstrapped.")
        return True
    
    print("📦 Bootstrapping Expo template...")
    
    if platform.system().lower().startswith("win"):
        npx = shutil.which("npx.cmd") or shutil.which("npx")
        if not npx:
            print("❌ Could not find npx in PATH.")
            return False
        command = [npx, "create-expo-app@latest", ".", "--template", "blank@sdk-54", "--yes"]
    else:
        npx = shutil.which("npx") or shutil.which("npm")
        if npx:
            if "npx" in npx:
                command = [npx, "create-expo-app@latest", ".", "--template", "blank@sdk-54", "--yes"]
            else:
                command = [npx, "exec", "create-expo-app@latest", "--", ".", "--template", "blank@sdk-54", "--yes"]
        else:
            print("❌ Could not find npx or npm in PATH.")
            return False

    try:
        print(f"ℹ Running: {' '.join(command)}")
        # Keep output unbuffered so users can see download/progress logs in real time.
        result = subprocess.run(
            command,
            cwd=str(TOOL_BASE_OUTPUT),
            text=True,
            check=False,
            timeout=900,
            env={**os.environ, "CI": "1"},
        )
        
        if result.returncode != 0:
            print(f"❌ Expo bootstrap failed with exit code: {result.returncode}")
            return False
        
        TOOL_BOOTSTRAP_MARKER.write_text("ok\n", encoding="utf-8")
        print("✓ Expo template created successfully.")
        return True
        
    except Exception as e:
        print(f"❌ Error during Expo bootstrap: {e}")
        return False

def clean_default_src_files() -> None:
    """Remove default src files"""
    print("🧹 Cleaning default src files")
    remove_default_src_files()
    print("✓ Default src files removed (JSX-only mode).")


def install_tracked_packages() -> None:
    """Install tracked dependencies using npm so package.json is updated by npm."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT, _read_dependency_registry
    
    print("📝 Installing tracked dependencies with npm...")
    
    package_json = TOOL_BASE_OUTPUT / "package.json"
    if not package_json.exists():
        print("❌ package.json not found.")
        return
    
    registry_file = TOOL_BASE_OUTPUT / ".agent_dependency_registry.json"
    if not registry_file.exists():
        print("✓ No new dependencies to sync.")
        return
    
    try:
        registry = _read_dependency_registry()

        npm_executable = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm_executable:
            print("❌ npm executable not found in PATH.")
            return

        deps = registry.get("dependencies", [])
        dev_deps = registry.get("devDependencies", [])

        deps = sorted({str(item).strip() for item in deps if str(item).strip()})
        dev_deps = sorted({str(item).strip() for item in dev_deps if str(item).strip()})

        if deps:
            cmd = [npm_executable, "install", *deps]
            result = subprocess.run(
                cmd,
                cwd=str(TOOL_BASE_OUTPUT),
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                print(f"❌ npm install failed for dependencies: {stderr[:500]}")
                return

        if dev_deps:
            cmd = [npm_executable, "install", "-D", *dev_deps]
            result = subprocess.run(
                cmd,
                cwd=str(TOOL_BASE_OUTPUT),
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                print(f"❌ npm install failed for devDependencies: {stderr[:500]}")
                return

        total = len(deps) + len(dev_deps)
        print(f"✓ Installed tracked libraries: {total}.")

        # Clear registry after successful install
        registry_file.write_text(json.dumps({"dependencies": [], "devDependencies": []}, indent=2), encoding="utf-8")
        
    except Exception as e:
        print(f"❌ Error syncing package.json: {e}")


def sanitize_package_json_dependencies() -> None:
    """Fix invalid package.json dependency keys produced by model output."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT

    package_json = TOOL_BASE_OUTPUT / "package.json"
    if not package_json.exists():
        return

    def normalize_name(name: str) -> str:
        key = str(name).strip()
        if "/" in key and not key.startswith("@"):
            return f"@{key}"
        return key

    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"⚠ Could not parse package.json for dependency sanitization: {exc}")
        return

    changed = False
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        values = payload.get(section)
        if not isinstance(values, dict):
            continue

        fixed: dict[str, str] = {}
        for name, version in values.items():
            normalized_name = normalize_name(name)
            if normalized_name != name:
                changed = True
            # Prefer existing normalized key if present, otherwise take current version.
            if normalized_name not in fixed:
                fixed[normalized_name] = version
            elif fixed[normalized_name] in ("", None) and version not in ("", None):
                fixed[normalized_name] = version

        payload[section] = fixed

    if changed:
        package_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print("✓ package.json dependency names sanitized.")


def run(content_prompt: str = "Create a Todo App") -> str:
    """Run the MVP app generator with minimal token usage and fixed app naming."""
    
    load_dotenv(dotenv_path=_REPO_ROOT / ".env", override=True)
    
    app_folder = "MyApp"
    
    print("🎯 Generating MVP: MyApp")
    print(f"📂 Output folder: GeneratedMVP/{app_folder}/\n")
    
    # Configure dynamic BASE_OUTPUT paths before bootstrap
    set_base_output_path(app_folder)
    
    # Step 1: Bootstrap Expo template directly (not through agents)
    if not bootstrap_expo_directly():
        print("❌ Failed to bootstrap Expo template. Aborting.")
        return "bootstrap_failed"
    
    # Step 2: Create/preserve index.js entry point (required by Expo)
    create_index_js()
    
    # Step 3: Set static app name
    update_app_json()
    
    # Step 4: Clean default src files (preserves index.js)
    clean_default_src_files()
    
    # Step 5: Run crew with agents to generate only src files
    print("\n🚀 Running agent crew for src code generation...")
    inputs = {
        "content_prompt": content_prompt,
    }
    
    crew_output = _run_crew_with_retries(inputs)

    # Step 6: Run Debugging Agent on planner/architect/coding outputs and apply fixes.
    print("\n🩺 Running Debugging Agent for static analysis and final corrections...")
    planner_output, architecture_output, coding_output = _extract_task_outputs(crew_output)

    try:
        corrected_codebase_json = run_debugging_agent(
            planner_output=planner_output,
            architecture_output=architecture_output,
            coding_output=coding_output,
        )

        corrected_files = _apply_corrected_codebase(corrected_codebase_json)
        print(f"✓ Debugging Agent corrections applied: {corrected_files} files updated.")
    except Exception as debug_error:
        print(f"⚠ Debugging Agent failed; continuing with generated files. Reason: {debug_error}")
    
    # Step 7: Fix invalid dependency names before install
    sanitize_package_json_dependencies()

    # Step 8: Sync dependencies to package.json
    install_tracked_packages()
    
    print("\n✅ MVP app generation complete!")
    return "crew_completed"


if __name__ == "__main__":
    run()

