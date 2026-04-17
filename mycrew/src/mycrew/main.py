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

from mycrew.crew import Mycrew
from mycrew.tools.custom_tool import (
    set_base_output_path,
    remove_default_src_files,
)


def _find_executable(*names: str) -> str | None:
    """Find an executable reliably across local/dev and containerized environments."""
    candidates = [name for name in names if name]

    for name in candidates:
        resolved = shutil.which(name)
        if resolved:
            return resolved

    common_paths = [
        # Linux/container defaults
        "/usr/local/bin/npm",
        "/usr/bin/npm",
        "/usr/local/bin/npx",
        "/usr/bin/npx",
        # Common Windows installs
        r"C:\Program Files\nodejs\npm.cmd",
        r"C:\Program Files\nodejs\npx.cmd",
    ]
    for path in common_paths:
        file_name = Path(path).name.lower()
        if file_name in {name.lower() for name in candidates} and Path(path).exists():
            return path

    probe_cmd = ["where", candidates[0]] if platform.system().lower().startswith("win") else ["which", candidates[0]]
    try:
        probe = subprocess.run(
            probe_cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if probe.returncode == 0:
            first_line = (probe.stdout or "").strip().splitlines()
            if first_line:
                return first_line[0].strip()
    except Exception:
        pass

    return None


def _resolve_node_tools() -> tuple[str | None, str | None]:
    """Resolve npx and npm executables with PATH and non-PATH fallbacks."""
    env_npx = os.getenv("NPX_EXECUTABLE", "").strip() or None
    env_npm = os.getenv("NPM_EXECUTABLE", "").strip() or None

    npx_executable = env_npx or _find_executable("npx", "npx.cmd")
    npm_executable = env_npm or _find_executable("npm", "npm.cmd")
    return npx_executable, npm_executable


def _is_tool_call_payload_error(exc: Exception) -> bool:
    """Detect Groq tool_use_failed errors across all exception types."""
    text = str(exc)
    error_type = type(exc).__name__
    
    # Check for common indicators of tool_use_failed
    is_tool_error = (
        "tool_use_failed" in text or
        '"code":"tool_use_failed"' in text or
        "Failed to call a function" in text
    )
    
    # Log detection attempt for debugging
    if is_tool_error:
        print(f"[DEBUG] Tool-call error detected: {error_type} | {text[:200]}")
    
    return is_tool_error


def _run_crew_with_retries(inputs: dict[str, str]) -> None:
    """Run crew with automatic retry on Groq tool_use_failed errors."""
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            print(f"[Crew Attempt {attempt}/{attempts}] Starting crew kickoff...")
            Mycrew().crew().kickoff(inputs=inputs)
            print(f"[Crew Attempt {attempt}/{attempts}] ✅ Success!")
            return
        except Exception as exc:
            is_retryable = _is_tool_call_payload_error(exc)
            has_attempts_left = attempt < attempts
            
            if is_retryable and has_attempts_left:
                print(
                    f"⚠ Tool-call payload rejected by provider (attempt {attempt}/{attempts}). "
                    f"Retrying in 2 seconds..."
                )
                import time
                time.sleep(2)  # Brief pause before retry
                continue
            
            # No retry: either not a tool error, or out of attempts
            print(f"[Crew Attempt {attempt}/{attempts}] ❌ Failed (retryable={is_retryable}, attempts_left={has_attempts_left})")
            raise

def create_index_js() -> None:
    """Create/preserve index.js entry point that points to src/App.
    
    NOTE: Deprecated for Snack SDK flow. Agents now write App.js to root directly.
    Kept for local Expo Go testing only (not used in Snack upload).
    
    This is required by Expo as the main entry point for local development.
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
    print("✓ index.js entry point created (for local Expo Go testing only)")

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

    npx_executable, npm_executable = _resolve_node_tools()

    is_windows = platform.system().lower().startswith("win")
    if is_windows:
        if npx_executable:
            command = f'"{npx_executable}" create-expo-app@latest . --template blank@sdk-54 --yes --no-install'
        elif npm_executable:
            command = f'"{npm_executable}" exec create-expo-app@latest -- . --template blank@sdk-54 --yes --no-install'
        else:
            print(f"❌ Could not find npx/npm. PATH={os.getenv('PATH', '')[:400]}")
            return False
    else:
        if npx_executable:
            command = [npx_executable, "create-expo-app@latest", ".", "--template", "blank@sdk-54", "--yes", "--no-install"]
        elif npm_executable:
            command = [npm_executable, "exec", "create-expo-app@latest", "--", ".", "--template", "blank@sdk-54", "--yes", "--no-install"]
        else:
            print(f"❌ Could not find npx/npm. PATH={os.getenv('PATH', '')[:400]}")
            return False

    try:
        result = subprocess.run(
            command,
            cwd=str(TOOL_BASE_OUTPUT),
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
            shell=isinstance(command, str),
        )
        
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            print(f"❌ Expo bootstrap failed: {stderr[:500]}")
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


def _npm_install_with_fallback(npm_executable: str, cwd: Path, args: list[str]) -> tuple[bool, str]:
    """Run npm install and fall back to legacy peer deps when resolver is too strict."""
    primary = subprocess.run(
        [npm_executable, "install", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if primary.returncode == 0:
        return True, ""

    stderr = (primary.stderr or "").strip()
    if "ERESOLVE" not in stderr:
        return False, stderr

    retry = subprocess.run(
        [npm_executable, "install", "--legacy-peer-deps", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    if retry.returncode == 0:
        print("⚠ npm install required --legacy-peer-deps fallback.")
        return True, ""

    return False, (retry.stderr or "").strip() or stderr


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

        _, npm_executable = _resolve_node_tools()
        if not npm_executable:
            print(f"❌ npm executable not found. PATH={os.getenv('PATH', '')[:400]}")
            return

        deps = registry.get("dependencies", [])
        dev_deps = registry.get("devDependencies", [])

        deps = sorted({str(item).strip() for item in deps if str(item).strip()})
        dev_deps = sorted({str(item).strip() for item in dev_deps if str(item).strip()})

        if deps:
            ok, stderr = _npm_install_with_fallback(npm_executable, TOOL_BASE_OUTPUT, deps)
            if not ok:
                print(f"❌ npm install failed for dependencies: {stderr[:500]}")
                return

        if dev_deps:
            ok, stderr = _npm_install_with_fallback(npm_executable, TOOL_BASE_OUTPUT, ["-D", *dev_deps])
            if not ok:
                print(f"❌ npm install failed for devDependencies: {stderr[:500]}")
                return

        total = len(deps) + len(dev_deps)
        print(f"✓ Installed tracked libraries: {total}.")

        # Clear registry after successful install
        registry_file.write_text(json.dumps({"dependencies": [], "devDependencies": []}, indent=2), encoding="utf-8")
        
    except Exception as e:
        print(f"❌ Error syncing package.json: {e}")


def run(content_prompt: str = "Create a Todo App") -> str:
    """Run the MVP app generator with minimal token usage and fixed app naming."""
    
    load_dotenv(override=True)
    
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
    
    _run_crew_with_retries(inputs)
    
    # Step 6: Sync dependencies to package.json
    # Skipped for Snack SDK-only flow.
    # install_tracked_packages()
    
    print("\n✅ MVP app generation complete!")
    return "crew_completed"


if __name__ == "__main__":
    run()

