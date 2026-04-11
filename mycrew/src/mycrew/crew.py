import json
import os

from crewai import Agent, Crew, Process, Task
from crewai import LLM
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from mycrew.tools.custom_tool import (
    FileReaderTool,
    FileWriterTool,
    TrackDependencyTool,
)


def _extract_response_text(response) -> str:
    """Best-effort extraction of model text across different response shapes."""
    candidates = [
        getattr(response, "raw", None),
        getattr(response, "text", None),
        getattr(response, "content", None),
        getattr(response, "output", None),
    ]

    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()

    fallback = str(response).strip()
    return fallback


def _normalize_json_candidate(raw_output: str) -> str:
    text = (raw_output or "").strip()
    if not text:
        return text

    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json\n"):
                text = text[5:].strip()
            elif text.lower() == "json":
                text = ""

    if text and text[0] != "{":
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

    return text.strip()


def _parse_debug_codebase_json(raw_output: str) -> dict[str, str]:
    normalized = _normalize_json_candidate(raw_output)
    if not normalized:
        raise ValueError("Debugging Agent returned empty output.")

    parsed = json.loads(normalized)
    if not isinstance(parsed, dict):
        raise ValueError("Debugging Agent output must be a JSON object mapping file paths to code.")

    for path, code in parsed.items():
        if not isinstance(path, str) or not isinstance(code, str):
            raise ValueError("Debugging Agent JSON must map string file paths to string code values.")

    return parsed


def run_debugging_agent(
    planner_output: str,
    architecture_output: str,
    coding_output: str,
    model: str = "groq/llama-3.3-70b-versatile",
) -> str:
    """Run the Debugging Agent and return a strict JSON codebase map.

    The return value is always a JSON object string where keys are file paths
    and values are raw file contents.
    """
    system_prompt = """You are Gwen Debugging Agent, a Staff-level React Native + Expo debugging expert.

MISSION
You receive outputs from the Planner, Architecture, and Coding agents and must produce a corrected, bug-free React Native MVP codebase that runs in Expo Snack / Expo Go.

INPUTS
1) Planner output: product requirements and feature scope.
2) Architecture output: file graph, navigation, contracts, imports, and component responsibilities.
3) Coding output: generated codebase content.

REQUIRED ANALYSIS CHECKLIST (STATIC ANALYSIS)
Perform exhaustive static validation across all provided files:
- Missing imports and unused/incorrect imports.
- Cross-file import path correctness and exported symbol alignment.
- Syntax errors (JavaScript/JSX/JSON), invalid JSX, and malformed object literals.
- Hook rules violations: hooks inside conditions/loops/nested funcs, invalid dependency arrays, stale closure risks, and side-effect misuse.
- Missing required props and prop name mismatches.
- Navigation parameter contract mismatches between route definitions and route usage.
- Expo compatibility: reject bare React Native native modules that are not Expo-managed compatible unless replaced with Expo SDK alternatives.
- Package consistency: ensure required dependencies for used APIs exist in package.json.
- Runtime safety checks via static reasoning: null/undefined guards, async error handling, key props for lists, and safe state initialization.

STYLING CONSTRAINTS
- Enforce React Native StyleSheet.create usage for component styling.
- Replace inline style objects with StyleSheet entries unless style is truly dynamic and unavoidable.
- Do not use web-only styling systems/frameworks (e.g., CSS files, styled-components web patterns, Tailwind-web utilities) unless they are Expo-compatible RN-native patterns already configured.

ARCHITECTURE ALIGNMENT RULES
- Preserve feature scope from Planner output (no random feature additions).
- Preserve and reconcile architecture contracts from Architecture output.
- Ensure every referenced file import actually exists and every referenced export is implemented.
- Ensure navigation names, params, and screen registration are fully consistent across files.

OUTPUT FORMAT (STRICT)
- Return ONLY a single valid JSON object.
- JSON keys: relative file paths such as "App.js", "components/Button.js", "package.json".
- JSON values: raw code strings for each file.
- Do not include markdown, code fences, commentary, explanations, or extra keys outside the file map.
- Ensure JSON is parseable with standard JSON.parse.

QUALITY BAR
- Code must be Expo Snack ready.
- Keep implementation minimal, clean, and MVP-focused.
- No placeholders, TODOs, pseudo-code, or incomplete stubs.
- If a file is unchanged but required, include its final corrected content anyway.
"""

    effective_model = os.getenv("CODE_DEBUGGER_LLM") or model

    debug_agent = Agent(
        role="Staff React Native Expo Debugging Agent",
        goal="Produce a bug-free Expo Snack-ready MVP codebase as strict JSON",
        backstory=system_prompt,
        llm=LLM(model=effective_model, temperature=0),
        allow_delegation=False,
        verbose=True,
        max_iter=2,
        max_retry_limit=2,
        memory=False,
        max_tokens=12000,
    )

    prompt = f"""Planner Output:
{planner_output}

Architecture Output:
{architecture_output}

Coding Output:
{coding_output}

Return only the corrected final codebase as strict JSON."""

    response = debug_agent.kickoff(prompt)
    raw_output = _extract_response_text(response)

    try:
        parsed = _parse_debug_codebase_json(raw_output)
    except Exception as first_error:
        repair_prompt = f"""Your previous response was invalid for strict JSON parsing.

Return ONLY a single valid JSON object where:
- keys are relative file paths
- values are raw file content strings

Do not include markdown, code fences, commentary, or extra text.

Previous invalid output:
{raw_output}
"""
        repair_response = debug_agent.kickoff(repair_prompt)
        repaired_raw_output = _extract_response_text(repair_response)
        try:
            parsed = _parse_debug_codebase_json(repaired_raw_output)
        except Exception as second_error:
            raise ValueError(
                "Debugging Agent failed to return strict JSON after one repair attempt. "
                f"First parse error: {first_error}. Second parse error: {second_error}."
            ) from second_error

    return json.dumps(parsed, indent=2, ensure_ascii=False)

def _required_llm_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required LLM environment variable: {name}")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default

@CrewBase
class Mycrew():
    """Mycrew crew that plans, designs, and builds a multi-file codebase from a prompt."""

    agents: list[BaseAgent]
    tasks: list[Task]
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def planner(self) -> Agent:
        planner_llm = LLM(model=_required_llm_env("PLANNER_LLM"))
        return Agent(
            config=self.agents_config['planner'],
            llm=planner_llm,
            verbose=False,
            max_tokens=1000,
        )

    @agent
    def architect(self) -> Agent:
        architect_llm = LLM(model=_required_llm_env("ARCHITECT_LLM"))
        return Agent(
            config=self.agents_config['architect'],
            llm=architect_llm,
            verbose=False,  # Disable verbose to reduce context
            max_tokens=4000,  # Reduced from 8000 (fewer files = shorter spec)
        )

    @agent
    def feature_builder(self) -> Agent:
        feature_llm = LLM(
            model=_required_llm_env("FEATURE_BUILDER_LLM"),
            temperature=0,
        )
        # Strict limits to prevent request payloads exceeding Groq's 8KB tool parameter limit.
        # Fewer iterations + output length limit = smaller context accumulation.
        max_iter = max(_int_env("FEATURE_MAX_ITER", 10), 8)  # Reduced from 20 to 10
        return Agent(
            config=self.agents_config['feature_builder'], 
            llm=feature_llm,
            tools=[FileReaderTool(), FileWriterTool(), TrackDependencyTool()],
            verbose=False,  # Disable verbose to reduce context size
            max_iter=max_iter,
            max_tokens=2000,  # Force concise outputs (was unlimited)
            max_retry_limit=2,  # Reduced from 4
            allow_delegation=False,
            memory=False,
            respect_context_window=True,  # Auto-truncate if needed
        )

    @task
    def plan_requirements(self) -> Task:
        return Task(
            config=self.tasks_config['plan_requirements'],
        )

    @task
    def design_architecture(self) -> Task:
        return Task(
            config=self.tasks_config['design_architecture'], 
        )

    @task
    def implement_mvp_features(self) -> Task:
        return Task(
            config=self.tasks_config['implement_mvp_features'],  
            tools=[FileReaderTool(), FileWriterTool(), TrackDependencyTool()],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the multi-agent crew for planning, architecture, and implementation."""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            planning=False,
            verbose=True,
            max_rpm=2,
            cache=True,
        )
