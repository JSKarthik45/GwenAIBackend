#!/usr/bin/env python
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from crewai import Agent, LLM, Task
from dotenv import load_dotenv

# Ensure the package root (…/mycrew/src) is on sys.path when run directly
_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from mycrew.crew import Mycrew
from mycrew.tools.custom_tool import (
    FileReaderTool,
    FileWriterTool,
    TrackDependencyTool,
    set_base_output_path,
    remove_default_src_files,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_CACHE_DIR = REPO_ROOT / "TemplateMVP"


def _find_executable(*names: str) -> str | None:
    """Find an executable reliably across local/dev and containerized environments."""
    candidates = [name for name in names if name]

    for name in candidates:
        resolved = shutil.which(name)
        if resolved:
            return resolved

    common_paths = [
        "/usr/local/bin/npm",
        "/usr/bin/npm",
        "/usr/local/bin/npx",
        "/usr/bin/npx",
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


def _copy_template_to_output(template_dir: Path, output_dir: Path) -> None:
    """Copy the TemplateMVP Expo template into the target MVP folder."""
    if output_dir.exists():
        shutil.rmtree(output_dir)

    shutil.copytree(
        template_dir,
        output_dir,
        ignore=shutil.ignore_patterns("node_modules", ".expo", ".expo-shared"),
    )


def _is_tool_call_payload_error(exc: Exception) -> bool:
    """Detect Groq tool_use_failed errors across all exception types."""
    text = str(exc)
    is_tool_error = (
        "tool_use_failed" in text or
        '"code":"tool_use_failed"' in text or
        "Failed to call a function" in text
    )
    if is_tool_error:
        print(f"[DEBUG] Tool-call error detected: {type(exc).__name__} | {text[:200]}")
    return is_tool_error


def _run_crew_with_retries(inputs: dict[str, str]) -> None:
    """Run crew with automatic retry on Groq tool_use_failed errors."""
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            print(f"[Crew Attempt {attempt}/{attempts}] Starting crew kickoff...")
            crew_builder = Mycrew()
            crew_instance = crew_builder.crew()
            _append_debug_runtime_task(crew_builder, crew_instance)
            crew_instance.kickoff(inputs=inputs)
            print(f"[Crew Attempt {attempt}/{attempts}] Success!")
            return
        except Exception as exc:
            is_retryable = _is_tool_call_payload_error(exc)
            has_attempts_left = attempt < attempts

            if is_retryable and has_attempts_left:
                print(
                    f"Tool-call payload rejected by provider (attempt {attempt}/{attempts}). "
                    f"Retrying in 2 seconds..."
                )
                time.sleep(2)
                continue

            print(f"[Crew Attempt {attempt}/{attempts}] Failed (retryable={is_retryable})")
            raise


def _resolve_debugger_model() -> str:
    """Resolve model for runtime debugger agent with safe fallbacks."""
    for env_name in (
        "REACT_NATIVE_DEBUGGER_LLM",
        "FEATURE_BUILDER_LLM",
        "SETTINGS_SCREEN_BUILDER_LLM",
        "HOME_SCREEN_BUILDER_LLM",
    ):
        value = os.getenv(env_name)
        if value:
            return value
    raise ValueError(
        "Missing required LLM environment variable for debugger agent: "
        "set REACT_NATIVE_DEBUGGER_LLM or FEATURE_BUILDER_LLM"
    )


def debugger_throttle(step_output) -> None:
    """Throttle only debugger agent steps to reduce provider TPM spikes."""
    _ = step_output
    time.sleep(10)


def _append_debug_runtime_task(crew_builder: Mycrew, crew_instance) -> None:
    """Initialize the runtime debugger agent and append its task as the final crew step."""
    if "react_native_debugger" not in crew_builder.agents_config:
        raise ValueError("agents.yaml missing required key: react_native_debugger")
    if "debug_runtime_logic" not in crew_builder.tasks_config:
        raise ValueError("tasks.yaml missing required key: debug_runtime_logic")

    debugger_agent = Agent(
        config=crew_builder.agents_config["react_native_debugger"],
        llm=LLM(model=_resolve_debugger_model(), temperature=0),
        tools=[FileReaderTool(), FileWriterTool(), TrackDependencyTool()],
        step_callback=debugger_throttle,
        verbose=False,
        max_iter=6,
        max_tokens=1400,
        max_retry_limit=1,
        allow_delegation=False,
        memory=False,
        respect_context_window=True,
    )
    debug_task = Task(
        config=crew_builder.tasks_config["debug_runtime_logic"],
        agent=debugger_agent,
        tools=[FileReaderTool(), FileWriterTool(), TrackDependencyTool()],
        context=[],
    )

    crew_instance.agents.append(debugger_agent)
    crew_instance.tasks.append(debug_task)

def create_index_js() -> None:
    """Preserve template index.js entry point (App.js at root)."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT

    index_file = TOOL_BASE_OUTPUT / "index.js"
    if index_file.exists():
        print("Preserved template index.js entry point")
    else:
        print("index.js not found in template output; skipping")

def update_app_json() -> None:
    """Set static app identity in app.json."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT

    app_json = TOOL_BASE_OUTPUT / "app.json"
    if not app_json.exists():
        print("app.json not found, skipping dynamic name update")
        return

    try:
        config = json.loads(app_json.read_text(encoding="utf-8"))
        config["expo"]["name"] = "MyApp"
        config["expo"]["slug"] = "myapp"
        app_json.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        print("app.json updated: name='MyApp', slug='myapp'")
    except Exception as e:
        print(f"Could not update app.json: {e}")

def bootstrap_expo_directly() -> bool:
    """Create TemplateMVP once (if missing), then copy it for each MVP run."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT, BOOTSTRAP_MARKER as TOOL_BOOTSTRAP_MARKER

    cached_package_json = TEMPLATE_CACHE_DIR / "package.json"

    if cached_package_json.exists():
        print(f"Reusing TemplateMVP: {TEMPLATE_CACHE_DIR}")
    else:
        print("Creating TemplateMVP with Expo blank@sdk-54 (one-time bootstrap)...")

        if TEMPLATE_CACHE_DIR.exists():
            shutil.rmtree(TEMPLATE_CACHE_DIR)
        TEMPLATE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        npx_executable, npm_executable = _resolve_node_tools()

        is_windows = platform.system().lower().startswith("win")
        if is_windows:
            if npx_executable:
                command = f'"{npx_executable}" create-expo-app@latest . --template blank@sdk-54 --yes --no-install'
            elif npm_executable:
                command = f'"{npm_executable}" exec create-expo-app@latest -- . --template blank@sdk-54 --yes --no-install'
            else:
                print(f"Could not find npx/npm. PATH={os.getenv('PATH', '')[:400]}")
                return False
        else:
            if npx_executable:
                command = [npx_executable, "create-expo-app@latest", ".", "--template", "blank@sdk-54", "--yes", "--no-install"]
            elif npm_executable:
                command = [npm_executable, "exec", "create-expo-app@latest", "--", ".", "--template", "blank@sdk-54", "--yes", "--no-install"]
            else:
                print(f"Could not find npx/npm. PATH={os.getenv('PATH', '')[:400]}")
                return False

        try:
            result = subprocess.run(
                command,
                cwd=str(TEMPLATE_CACHE_DIR),
                capture_output=True,
                text=True,
                check=False,
                timeout=900,
                shell=isinstance(command, str),
            )

            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                print(f"Expo template bootstrap failed: {stderr[:500]}")
                return False

            print("TemplateMVP created successfully.")
        except Exception as e:
            print(f"Error creating TemplateMVP: {e}")
            return False

    try:
        _copy_template_to_output(TEMPLATE_CACHE_DIR, TOOL_BASE_OUTPUT)
        TOOL_BOOTSTRAP_MARKER.write_text("ok\n", encoding="utf-8")
        print(f"Copied template into MVP output: {TOOL_BASE_OUTPUT}")
        return True
    except Exception as e:
        print(f"Failed to copy template into output: {e}")
        return False

def clean_default_src_files() -> None:
    """Run template-safe cleanup for legacy files only."""
    print("Running template-safe cleanup")
    remove_default_src_files()
    print("Template-safe cleanup complete.")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def fix_absolute_src_imports(base_output: Path) -> None:
    """Post-process all generated JS files in src/ to rewrite absolute 'src/...' imports.

    The AI agents sometimes emit imports like:
        import Theme from 'src/Theme';
        import Button from 'src/Button.js';

    Metro (Expo bundler) cannot resolve these. This function deterministically
    rewrites every such import to a safe relative form:
        import Theme from './Theme';
        import Button from './Button';
    """
    src_dir = base_output / "src"
    if not src_dir.exists():
        print("fix_absolute_src_imports: src/ directory not found, skipping.")
        return

    absolute_src_pattern = re.compile(
        r"(from\s+['\"])src/([^'\"]+)(['\"])"
    )

    fixed_count = 0

    def _rewrite_match(m: re.Match) -> str:
        quote_open = m.group(1)
        module_name = m.group(2)
        quote_close = m.group(3)
        clean = module_name.removesuffix(".js")
        return f"{quote_open}./{clean}{quote_close}"

    for js_file in src_dir.rglob("*.js"):
        try:
            original = js_file.read_text(encoding="utf-8")
        except Exception as e:
            print(f"Could not read {js_file.name}: {e}")
            continue

        patched = absolute_src_pattern.sub(_rewrite_match, original)

        if patched != original:
            try:
                js_file.write_text(patched, encoding="utf-8")
                fixed_count += 1
                print(f"  Fixed absolute 'src/' imports in: {js_file.name}")
            except Exception as e:
                print(f"Could not write {js_file.name}: {e}")

    if fixed_count:
        print(f"fix_absolute_src_imports: rewrote absolute imports in {fixed_count} file(s).")
    else:
        print("fix_absolute_src_imports: no absolute 'src/' imports found.")


def _ensure_content_exists() -> None:
    """Guarantee src/Content.js exists with a working fallback if builders failed."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT

    content_file = TOOL_BASE_OUTPUT / "src" / "Content.js"

    if content_file.exists():
        text = content_file.read_text(encoding="utf-8")
        # Check it's not just the template placeholder
        if "Loading your app" not in text and "export default" in text:
            print("Content verification passed: src/Content.js exists with real content.")
            return

    print("Builder output missing or placeholder. Applying fallback Content.js.")
    _write_file(
        content_file,
        """import React, { useCallback, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

const createItem = (title) => ({
    id: Date.now().toString() + Math.random().toString(16).slice(2, 6),
    title: title.trim(),
    done: false,
});

const Content = () => {
    const [items, setItems] = useState([]);
    const [text, setText] = useState('');

    const addItem = useCallback(() => {
        const t = text.trim();
        if (!t) return;
        setItems((prev) => [createItem(t), ...prev]);
        setText('');
    }, [text]);

    const toggleItem = useCallback((id) => {
        setItems((prev) => prev.map((i) => (i.id === id ? { ...i, done: !i.done } : i)));
    }, []);

    const removeItem = useCallback((id) => {
        setItems((prev) => prev.filter((i) => i.id !== id));
    }, []);

    return (
        <View style={styles.container}>
            <Text style={styles.heading}>My Tasks</Text>
            <View style={styles.inputRow}>
                <TextInput
                    style={styles.input}
                    placeholder="Add a task..."
                    value={text}
                    onChangeText={setText}
                />
                <Pressable style={styles.addBtn} onPress={addItem}>
                    <Text style={styles.addBtnText}>Add</Text>
                </Pressable>
            </View>
            {items.length === 0 ? (
                <Text style={styles.empty}>No tasks yet</Text>
            ) : (
                <FlatList
                    data={items}
                    keyExtractor={(item) => item.id}
                    renderItem={({ item }) => (
                        <View style={styles.card}>
                            <Pressable style={styles.cardBody} onPress={() => toggleItem(item.id)}>
                                <Text style={[styles.cardTitle, item.done && styles.done]}>
                                    {item.done ? '\\u2713 ' : ''}{item.title}
                                </Text>
                            </Pressable>
                            <Pressable onPress={() => removeItem(item.id)}>
                                <Text style={styles.deleteText}>Delete</Text>
                            </Pressable>
                        </View>
                    )}
                />
            )}
        </View>
    );
};

const styles = StyleSheet.create({
    container: { flex: 1, gap: 12 },
    heading: { fontSize: 22, fontWeight: '700', color: '#1f2937' },
    inputRow: { flexDirection: 'row', gap: 8 },
    input: {
        flex: 1, borderWidth: 1, borderColor: '#d1d5db', borderRadius: 10,
        paddingHorizontal: 12, paddingVertical: 10, backgroundColor: '#fff',
    },
    addBtn: {
        backgroundColor: '#0f766e', borderRadius: 10,
        paddingHorizontal: 16, justifyContent: 'center',
    },
    addBtnText: { color: '#fff', fontWeight: '600' },
    empty: { color: '#9ca3af', marginTop: 20, textAlign: 'center' },
    card: {
        flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
        borderWidth: 1, borderColor: '#e5e7eb', borderRadius: 10,
        padding: 12, backgroundColor: '#fff', marginTop: 8,
    },
    cardBody: { flex: 1 },
    cardTitle: { fontSize: 15, color: '#111827' },
    done: { textDecorationLine: 'line-through', color: '#9ca3af' },
    deleteText: { color: '#be123c', fontWeight: '600', fontSize: 13 },
});

export default Content;
""",
    )
    print("Fallback Content.js written.")


def run(content_prompt: str = "Create a Todo App") -> str:
    """Run the MVP app generator with minimal token usage and fixed app naming."""

    load_dotenv(override=True)

    app_folder = "MyApp"

    print("Generating MVP: MyApp")
    print(f"Output folder: GeneratedMVP/{app_folder}/\n")

    # Configure dynamic BASE_OUTPUT paths before bootstrap
    set_base_output_path(app_folder)

    # Step 1: Bootstrap Expo template directly (not through agents)
    if not bootstrap_expo_directly():
        print("Failed to bootstrap Expo template. Aborting.")
        return "bootstrap_failed"

    # Step 2: Create/preserve index.js entry point (required by Expo)
    create_index_js()

    # Step 3: Set static app name
    update_app_json()

    # Step 4: Clean default src files (preserves index.js)
    clean_default_src_files()

    # Step 5: Run crew with agents to generate only src files
    print("\nRunning agent crew for src code generation...")
    inputs = {
        "content_prompt": content_prompt,
    }

    _run_crew_with_retries(inputs)

    # Step 6: Deterministically rewrite any absolute 'src/...' imports to relative './' imports.
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT
    fix_absolute_src_imports(TOOL_BASE_OUTPUT)

    # Step 7: Guarantee generated app has working Content.js
    _ensure_content_exists()

    print("\nMVP app generation complete!")
    return "crew_completed"


if __name__ == "__main__":
    run()
