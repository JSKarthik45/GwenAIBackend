from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
import os
from mycrew.tools.custom_tool import FileReaderTool, FileWriterTool


@CrewBase
class MycrewCrew:
    """Minimal three-agent crew for Expo app generation."""

    agents: List[BaseAgent]
    tasks: List[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def planner(self) -> Agent:
        return Agent(
            config=self.agents_config["planner"],  # type: ignore[index]
            llm=os.getenv("FEATURE_BUILDER_LLM") or os.getenv("OPENAI_MODEL_NAME") or "gpt-4o-mini",
            use_system_prompt=False,
            verbose=False,
            allow_delegation=False,
            memory=False,
        )

    @agent
    def architect(self) -> Agent:
        return Agent(
            config=self.agents_config["architect"],  # type: ignore[index]
            llm=os.getenv("FEATURE_BUILDER_LLM") or os.getenv("OPENAI_MODEL_NAME") or "gpt-4o-mini",
            use_system_prompt=False,
            verbose=False,
            allow_delegation=False,
            memory=False,
        )

    @agent
    def coder(self) -> Agent:
        return Agent(
            config=self.agents_config["coder"],  # type: ignore[index]
            llm=os.getenv("FEATURE_BUILDER_LLM") or os.getenv("OPENAI_MODEL_NAME") or "gpt-4o-mini",
            use_system_prompt=False,
            verbose=False,
            allow_delegation=False,
            memory=False,
            respect_context_window=True,
            tools=[FileReaderTool(), FileWriterTool()],
        )

    @task
    def plan_task(self) -> Task:
        return Task(
            config=self.tasks_config["plan_task"],  # type: ignore[index]
        )

    @task
    def architecture_task(self) -> Task:
        return Task(
            config=self.tasks_config["architecture_task"],  # type: ignore[index]
            context=[self.plan_task()],
        )

    @task
    def code_task(self) -> Task:
        return Task(
            config=self.tasks_config["code_task"],  # type: ignore[index]
            context=[self.architecture_task()],
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Expo app generation crew."""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=False,
            cache=False,
        )
