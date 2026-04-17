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
            max_tokens=1800,  # Keep architecture outputs concise
        )

    @agent
    def feature_builder(self) -> Agent:
        feature_llm = LLM(
            model=_required_llm_env("FEATURE_BUILDER_LLM"),
            temperature=0,
        )
        # Strict limits to prevent request payloads exceeding Groq's tool parameter limit.
        # Fewer iterations + output length limit = smaller context accumulation.
        max_iter = max(_int_env("FEATURE_MAX_ITER", 6), 4)
        return Agent(
            config=self.agents_config['feature_builder'], 
            llm=feature_llm,
            tools=[FileReaderTool(), FileWriterTool(), TrackDependencyTool()],
            verbose=False,  # Disable verbose to reduce context size
            max_iter=max_iter,
            max_tokens=1200,  # Force concise outputs
            max_retry_limit=1,  # Reduce repeated oversized retries
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
            max_rpm=6,
            cache=True,
        )
