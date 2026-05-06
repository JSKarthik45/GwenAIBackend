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

def _required_llm_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required LLM environment variable: {name}")
    return value


def _optional_llm_env(name: str, fallback_env: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    return _required_llm_env(fallback_env)


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
    """Simplified single-page MVP crew: plan, build, debug."""

    agents: list[BaseAgent]
    tasks: list[Task]
    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def planner(self) -> Agent:
        planner_llm = LLM(model=_required_llm_env("PLANNER_LLM"))
        return Agent(
            config=self.agents_config['planner'],  # type: ignore[index]
            llm=planner_llm,
            verbose=False,
            max_tokens=1500,
        )

    @agent
    def builder(self) -> Agent:
        feature_llm = LLM(
            model=_optional_llm_env("HOME_SCREEN_BUILDER_LLM", "FEATURE_BUILDER_LLM"),
            temperature=0,
        )
        max_iter = max(_int_env("FEATURE_MAX_ITER", 8), 5)
        return Agent(
            config=self.agents_config['builder'],  # type: ignore[index]
            llm=feature_llm,
            tools=[FileReaderTool(), FileWriterTool(), TrackDependencyTool()],
            verbose=False,
            max_iter=max_iter,
            max_tokens=1400,
            max_retry_limit=1,
            allow_delegation=False,
            memory=False,
            respect_context_window=True,
        )

    @agent
    def react_native_debugger(self) -> Agent:
        debugger_llm = LLM(
            model=_optional_llm_env("REACT_NATIVE_DEBUGGER_LLM", "FEATURE_BUILDER_LLM"),
            temperature=0,
        )
        return Agent(
            config=self.agents_config['react_native_debugger'],  # type: ignore[index]
            llm=debugger_llm,
            tools=[FileReaderTool(), FileWriterTool(), TrackDependencyTool()],
            verbose=False,
            max_iter=6,
            max_tokens=1400,
            max_retry_limit=1,
            allow_delegation=False,
            memory=False,
            respect_context_window=True,
        )

    @task
    def plan_requirements(self) -> Task:
        return Task(
            config=self.tasks_config['plan_requirements'],  # type: ignore[index]
        )

    @task
    def build_app(self) -> Task:
        return Task(
            config=self.tasks_config['build_app'],  # type: ignore[index]
            tools=[FileReaderTool(), FileWriterTool(), TrackDependencyTool()],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the simplified single-page crew."""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            planning=False,
            verbose=True,
            max_rpm=2,
            cache=True,
        )
