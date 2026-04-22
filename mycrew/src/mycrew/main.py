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
            crew_builder = Mycrew()
            crew_instance = crew_builder.crew()
            _append_debug_runtime_task(crew_builder, crew_instance)
            crew_instance.kickoff(inputs=inputs)
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
    time.sleep(65)


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
    )

    crew_instance.agents.append(debugger_agent)
    crew_instance.tasks.append(debug_task)

def create_index_js() -> None:
    """Preserve template index.js entry point (App.js at root)."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT

    index_file = TOOL_BASE_OUTPUT / "index.js"
    if index_file.exists():
        print("✓ Preserved template index.js entry point")
    else:
        print("⚠ index.js not found in template output; skipping")

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
    """Create TemplateMVP once (if missing), then copy it for each MVP run."""
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT, BOOTSTRAP_MARKER as TOOL_BOOTSTRAP_MARKER

    cached_package_json = TEMPLATE_CACHE_DIR / "package.json"

    if cached_package_json.exists():
        print(f"📦 Reusing TemplateMVP: {TEMPLATE_CACHE_DIR}")
    else:
        print("📦 Creating TemplateMVP with Expo blank@sdk-54 (one-time bootstrap)...")

        # Ensure partial cache content from failed runs is removed.
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
                cwd=str(TEMPLATE_CACHE_DIR),
                capture_output=True,
                text=True,
                check=False,
                timeout=900,
                shell=isinstance(command, str),
            )

            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                print(f"❌ Expo template bootstrap failed: {stderr[:500]}")
                return False

            print("✓ TemplateMVP created successfully.")
        except Exception as e:
            print(f"❌ Error creating TemplateMVP: {e}")
            return False

    try:
        _copy_template_to_output(TEMPLATE_CACHE_DIR, TOOL_BASE_OUTPUT)
        TOOL_BOOTSTRAP_MARKER.write_text("ok\n", encoding="utf-8")
        print(f"✓ Copied template into MVP output: {TOOL_BASE_OUTPUT}")
        return True
    except Exception as e:
        print(f"❌ Failed to copy template into output: {e}")
        return False

def clean_default_src_files() -> None:
    """Run template-safe cleanup for legacy files only."""
    print("🧹 Running template-safe cleanup")
    remove_default_src_files()
    print("✓ Template-safe cleanup complete.")


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _extract_local_imports(source: str) -> list[str]:
    """Extract relative import targets from JS/JSX source."""
    pattern = re.compile(r"import\\s+[^;]*?from\\s+['\"]([^'\"]+)['\"]")
    imports = pattern.findall(source)
    return [item for item in imports if item.startswith(".")]


def _extract_local_import_specs(source: str) -> list[tuple[str, str]]:
    """Extract (module_path, import_clause) pairs for relative imports."""
    pattern = re.compile(r"import\s+(.+?)\s+from\s+['\"]([^'\"]+)['\"]", re.S)
    specs: list[tuple[str, str]] = []
    for clause, module_path in pattern.findall(source):
        if module_path.startswith("."):
            specs.append((module_path, clause.strip()))
    return specs


def _parse_import_clause(clause: str) -> tuple[bool, set[str], bool]:
    """Return (needs_default, named_imports, is_namespace_import)."""
    normalized = " ".join(clause.split())
    if normalized.startswith("* as "):
        return (False, set(), True)

    needs_default = False
    named_imports: set[str] = set()

    brace_start = normalized.find("{")
    brace_end = normalized.rfind("}")

    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        # There is a named import block, optionally with a default import prefix.
        prefix = normalized[:brace_start].strip().rstrip(",").strip()
        if prefix:
            needs_default = True

        named_block = normalized[brace_start + 1:brace_end].strip()
        for raw_item in named_block.split(","):
            item = raw_item.strip()
            if not item:
                continue
            token = item.split(" as ")[0].strip()
            if token:
                named_imports.add(token)
    else:
        # Default import only.
        if normalized:
            needs_default = True

    return (needs_default, named_imports, False)


def _analyze_exports(module_source: str) -> tuple[bool, set[str], bool]:
    """Return (has_default_export, named_exports, has_export_star)."""
    has_default_export = bool(re.search(r"export\s+default\s+", module_source))
    has_export_star = bool(re.search(r"export\s+\*\s+from\s+['\"]", module_source))

    named_exports: set[str] = set()

    for name in re.findall(r"export\s+(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", module_source):
        named_exports.add(name)

    for export_block in re.findall(r"export\s*\{([^}]+)\}", module_source):
        for raw_item in export_block.split(","):
            item = raw_item.strip()
            if not item:
                continue
            if " as " in item:
                left, right = item.split(" as ", 1)
                left = left.strip()
                right = right.strip()
                if left == "default":
                    has_default_export = True
                elif right:
                    named_exports.add(right)
            else:
                named_exports.add(item)

    return (has_default_export, named_exports, has_export_star)


def _resolve_js_module(base_file: Path, local_import: str) -> Path | None:
    """Resolve a local JS import path to an existing file path if possible."""
    base_dir = base_file.parent
    candidate_base = (base_dir / local_import).resolve()

    candidates = []
    if candidate_base.suffix:
        candidates.append(candidate_base)
    else:
        candidates.extend(
            [
                candidate_base.with_suffix(".js"),
                candidate_base.with_suffix(".jsx"),
                candidate_base / "index.js",
                candidate_base / "index.jsx",
            ]
        )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _find_unresolved_imports(file_path: Path) -> list[str]:
    if not file_path.exists():
        return []

    source = file_path.read_text(encoding="utf-8")
    unresolved: list[str] = []
    for local_import in _extract_local_imports(source):
        resolved = _resolve_js_module(file_path, local_import)
        if resolved is None:
            unresolved.append(local_import)
    return unresolved


def _find_missing_dependency_edges(entry_file: Path) -> list[str]:
    """Recursively validate local imports from an entry file.

    Returns a list of missing dependency edges formatted as
    "relative/source.js -> ../missing/module".
    """
    if not entry_file.exists():
        return []

    visited: set[Path] = set()
    missing: list[str] = []

    def _walk(current_file: Path) -> None:
        resolved_current = current_file.resolve()
        if resolved_current in visited:
            return
        visited.add(resolved_current)

        source = current_file.read_text(encoding="utf-8")
        local_imports = _extract_local_imports(source)
        for local_import in local_imports:
            target = _resolve_js_module(current_file, local_import)
            if target is None:
                missing.append(f"{current_file.name} -> {local_import}")
                continue
            _walk(target)

    _walk(entry_file)
    return missing


def _find_invalid_import_contracts(entry_file: Path) -> list[str]:
    """Recursively validate local import contracts (named/default compatibility)."""
    if not entry_file.exists():
        return []

    visited: set[Path] = set()
    invalid: list[str] = []

    def _walk(current_file: Path) -> None:
        resolved_current = current_file.resolve()
        if resolved_current in visited:
            return
        visited.add(resolved_current)

        source = current_file.read_text(encoding="utf-8")
        import_specs = _extract_local_import_specs(source)

        for module_path, clause in import_specs:
            target = _resolve_js_module(current_file, module_path)
            if target is None:
                # Missing-file issues are handled by _find_missing_dependency_edges.
                continue

            needs_default, named_imports, is_namespace = _parse_import_clause(clause)
            if is_namespace:
                _walk(target)
                continue

            target_source = target.read_text(encoding="utf-8")
            has_default_export, named_exports, has_export_star = _analyze_exports(target_source)

            # If export-star is present, skip strict named checks because re-exports are dynamic.
            if needs_default and not has_default_export:
                invalid.append(f"{current_file.name} -> {module_path} (default import not exported)")

            if not has_export_star:
                for name in named_imports:
                    if name == "default":
                        if not has_default_export:
                            invalid.append(
                                f"{current_file.name} -> {module_path} (named default import requires default export)"
                            )
                    elif name not in named_exports:
                        invalid.append(
                            f"{current_file.name} -> {module_path} (named import '{name}' not exported)"
                        )

            _walk(target)

    _walk(entry_file)
    return invalid


def _contains_import_without_export(source: str) -> bool:
    """Detect JS modules that import from elsewhere but export nothing."""
    has_import = bool(re.search(r"^\s*import\s+.+\s+from\s+['\"][^'\"]+['\"]\s*;?\s*$", source, re.M))
    has_export = bool(re.search(r"\bexport\s+(default|\{|\*|const|let|var|function|class)\b", source))
    return has_import and not has_export


def _find_import_without_export_modules(base_output: Path) -> list[str]:
    """Find JS modules under src/content|shared|utils with imports but no exports."""
    root = base_output / "src"
    scan_dirs = [root / "content", root / "shared", root / "utils"]
    invalid_modules: list[str] = []

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for file_path in scan_dir.rglob("*.js"):
            source = file_path.read_text(encoding="utf-8")
            if _contains_import_without_export(source):
                invalid_modules.append(str(file_path.relative_to(base_output)).replace("\\", "/"))

    return invalid_modules


def _ensure_non_template_content() -> None:
    """Guarantee Home/Settings content files exist with usable, resolvable implementation.

    If builders fail to write required files or reference missing local modules,
    this fallback prevents shipping broken or unchanged content.
    """
    from mycrew.tools.custom_tool import BASE_OUTPUT as TOOL_BASE_OUTPUT

    home_file = TOOL_BASE_OUTPUT / "src" / "content" / "HomeContent.js"
    settings_file = TOOL_BASE_OUTPUT / "src" / "content" / "SettingsContent.js"
    storage_file = TOOL_BASE_OUTPUT / "src" / "utils" / "storage.js"

    home_needs_fallback = not home_file.exists()
    settings_needs_fallback = not settings_file.exists()

    if home_file.exists():
        home_text = home_file.read_text(encoding="utf-8")
        if "Home Content" in home_text and "Welcome!" in home_text:
            home_needs_fallback = True
        home_missing_tree = _find_missing_dependency_edges(home_file)
        if home_missing_tree:
            print(f"⚠ HomeContent dependency tree has missing imports: {home_missing_tree}")
            home_needs_fallback = True
        home_invalid_contracts = _find_invalid_import_contracts(home_file)
        if home_invalid_contracts:
            print(f"⚠ HomeContent import/export contract issues: {home_invalid_contracts}")
            home_needs_fallback = True

    if settings_file.exists():
        settings_text = settings_file.read_text(encoding="utf-8")
        if "Settings Content" in settings_text and "Customize your app" in settings_text:
            settings_needs_fallback = True
        settings_missing_tree = _find_missing_dependency_edges(settings_file)
        if settings_missing_tree:
            print(f"⚠ SettingsContent dependency tree has missing imports: {settings_missing_tree}")
            settings_needs_fallback = True
        settings_invalid_contracts = _find_invalid_import_contracts(settings_file)
        if settings_invalid_contracts:
            print(f"⚠ SettingsContent import/export contract issues: {settings_invalid_contracts}")
            settings_needs_fallback = True

    modules_missing_exports = _find_import_without_export_modules(TOOL_BASE_OUTPUT)
    if modules_missing_exports:
        print(f"⚠ JS modules with import statements but no exports: {modules_missing_exports}")
        home_needs_fallback = True
        settings_needs_fallback = True

    if not (home_needs_fallback or settings_needs_fallback):
        print("✓ Content verification passed: non-template files with resolved local imports.")
        return

    print("⚠ Builder output incomplete or invalid. Applying deterministic Home/Settings fallback files.")

    if not storage_file.exists():
        _write_file(
            storage_file,
            """import AsyncStorage from '@react-native-async-storage/async-storage';

const TODO_ITEMS_KEY = 'todoItems';
const SETTINGS_KEY = 'settings';

const saveJson = async (key, value) => {
    try {
        await AsyncStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
        console.warn('Storage save failed:', error?.message || error);
    }
};

const loadJson = async (key, fallbackValue) => {
    try {
        const raw = await AsyncStorage.getItem(key);
        if (!raw) return fallbackValue;
        return JSON.parse(raw);
    } catch (error) {
        console.warn('Storage load failed:', error?.message || error);
        return fallbackValue;
    }
};

export { TODO_ITEMS_KEY, SETTINGS_KEY, saveJson, loadJson };
""",
    )

    if home_needs_fallback:
        _write_file(
            home_file,
            """import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { TODO_ITEMS_KEY, loadJson, saveJson } from '../utils/storage';

const createTodo = (title, description) => ({
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    title: title.trim(),
    description: description.trim(),
    priority: 'medium',
});

const HomeContent = () => {
    const [items, setItems] = useState([]);
    const [title, setTitle] = useState('');
    const [description, setDescription] = useState('');
    const [error, setError] = useState('');

    useEffect(() => {
        let mounted = true;
        (async () => {
            const stored = await loadJson(TODO_ITEMS_KEY, []);
            if (mounted && Array.isArray(stored)) setItems(stored);
        })();
        return () => {
            mounted = false;
        };
    }, []);

    const persistItems = useCallback((nextItems) => {
        setItems(nextItems);
        saveJson(TODO_ITEMS_KEY, nextItems);
    }, []);

    const addItem = useCallback(() => {
        const safeTitle = title.trim();
        if (!safeTitle) {
            setError('Title is required.');
            return;
        }
        const next = [createTodo(title, description), ...items];
        persistItems(next);
        setTitle('');
        setDescription('');
        setError('');
    }, [description, items, persistItems, title]);

    const removeItem = useCallback((id) => {
        persistItems(items.filter((item) => item.id !== id));
    }, [items, persistItems]);

    const itemCountLabel = useMemo(() => `${items.length} task${items.length === 1 ? '' : 's'}`, [items.length]);

    return (
        <View style={styles.container}>
            <Text style={styles.heading}>My Tasks</Text>
            <Text style={styles.subheading}>{itemCountLabel}</Text>
            <TextInput style={styles.input} placeholder="Task title" value={title} onChangeText={setTitle} />
            <TextInput style={styles.input} placeholder="Task details (optional)" value={description} onChangeText={setDescription} />
            {!!error && <Text style={styles.error}>{error}</Text>}
            <Pressable style={styles.button} onPress={addItem}>
                <Text style={styles.buttonText}>Add Task</Text>
            </Pressable>
            {items.length === 0 ? (
                <Text style={styles.empty}>No tasks yet. Add your first task above.</Text>
            ) : (
                <FlatList
                    data={items}
                    keyExtractor={(item) => item.id}
                    renderItem={({ item }) => (
                        <View style={styles.card}>
                            <Text style={styles.cardTitle}>{item.title}</Text>
                            {!!item.description && <Text style={styles.cardDesc}>{item.description}</Text>}
                            <Pressable onPress={() => removeItem(item.id)}>
                                <Text style={styles.delete}>Delete</Text>
                            </Pressable>
                        </View>
                    )}
                />
            )}
        </View>
    );
};

const styles = StyleSheet.create({
    container: { flex: 1, padding: 16, gap: 10 },
    heading: { fontSize: 24, fontWeight: '700', color: '#1f2937' },
    subheading: { fontSize: 13, color: '#6b7280' },
    input: { borderWidth: 1, borderColor: '#d1d5db', borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, backgroundColor: '#fff' },
    button: { backgroundColor: '#0f766e', borderRadius: 10, paddingVertical: 12, alignItems: 'center' },
    buttonText: { color: '#fff', fontWeight: '600' },
    empty: { marginTop: 14, color: '#6b7280' },
    error: { color: '#b91c1c', fontSize: 12 },
    card: { marginTop: 10, borderWidth: 1, borderColor: '#e5e7eb', borderRadius: 12, padding: 12, backgroundColor: '#fff' },
    cardTitle: { fontSize: 16, fontWeight: '600', color: '#111827' },
    cardDesc: { marginTop: 4, color: '#4b5563' },
    delete: { marginTop: 10, color: '#be123c', fontWeight: '600' },
});

export default HomeContent;
""",
        )

    if settings_needs_fallback:
        _write_file(
            settings_file,
            """import React, { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Switch, Text, View } from 'react-native';
import { SETTINGS_KEY, loadJson, saveJson } from '../utils/storage';

const DEFAULT_SETTINGS = {
    dataPersistence: true,
    appLanguage: 'en',
};

const SettingsContent = () => {
    const [settings, setSettings] = useState(DEFAULT_SETTINGS);
    const [savedMessage, setSavedMessage] = useState('');

    useEffect(() => {
        let mounted = true;
        (async () => {
            const loaded = await loadJson(SETTINGS_KEY, DEFAULT_SETTINGS);
            if (mounted && loaded) setSettings({ ...DEFAULT_SETTINGS, ...loaded });
        })();
        return () => {
            mounted = false;
        };
    }, []);

    const togglePersistence = useCallback(() => {
        setSettings((prev) => ({ ...prev, dataPersistence: !prev.dataPersistence }));
        setSavedMessage('');
    }, []);

    const toggleLanguage = useCallback(() => {
        setSettings((prev) => ({ ...prev, appLanguage: prev.appLanguage === 'en' ? 'es' : 'en' }));
        setSavedMessage('');
    }, []);

    const saveSettings = useCallback(async () => {
        await saveJson(SETTINGS_KEY, settings);
        setSavedMessage('Saved. Settings will be reused next launch.');
    }, [settings]);

    return (
        <View style={styles.container}>
            <Text style={styles.heading}>Settings</Text>
            <View style={styles.row}>
                <Text style={styles.label}>Persist todo data</Text>
                <Switch value={settings.dataPersistence} onValueChange={togglePersistence} />
            </View>
            <View style={styles.row}>
                <Text style={styles.label}>Language: {settings.appLanguage.toUpperCase()}</Text>
                <Pressable style={styles.chip} onPress={toggleLanguage}>
                    <Text style={styles.chipText}>Toggle</Text>
                </Pressable>
            </View>
            <Pressable style={styles.saveButton} onPress={saveSettings}>
                <Text style={styles.saveButtonText}>Save Settings</Text>
            </Pressable>
            {!!savedMessage && <Text style={styles.notice}>{savedMessage}</Text>}
        </View>
    );
};

const styles = StyleSheet.create({
    container: { flex: 1, padding: 16, gap: 14 },
    heading: { fontSize: 24, fontWeight: '700', color: '#1f2937' },
    row: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#e5e7eb', borderRadius: 12, padding: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
    label: { fontSize: 15, color: '#111827' },
    chip: { backgroundColor: '#e0f2fe', borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6 },
    chipText: { color: '#0369a1', fontWeight: '600' },
    saveButton: { backgroundColor: '#0f766e', borderRadius: 10, paddingVertical: 12, alignItems: 'center' },
    saveButtonText: { color: '#fff', fontWeight: '600' },
    notice: { color: '#0f766e', fontSize: 13 },
});

export default SettingsContent;
""",
    )

    print("✓ Deterministic fallback applied for missing/invalid content replacements.")


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

    # Step 6: Guarantee generated app is not template-only if builders under-deliver.
    _ensure_non_template_content()
    
    # Step 7: Sync dependencies to package.json
    # Skipped for Snack SDK-only flow.
    # install_tracked_packages()
    
    print("\n✅ MVP app generation complete!")
    return "crew_completed"


if __name__ == "__main__":
    run()

