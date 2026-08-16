#!/usr/bin/env python
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from crewai import Crew

from mycrew.crew import MycrewCrew

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_DIR = REPO_ROOT / "TemplateMVP"
GENERATED_APP_DIR = REPO_ROOT / "GeneratedMVP" / "MyApp"


def _copy_template() -> bool:
    if GENERATED_APP_DIR.exists():
        shutil.rmtree(GENERATED_APP_DIR)
    shutil.copytree(TEMPLATE_DIR, GENERATED_APP_DIR, ignore=shutil.ignore_patterns("node_modules", ".expo", ".expo-shared"))
    print(f"✓ Copied template into MVP output: {GENERATED_APP_DIR}")
    return True


def _build_crew() -> Crew:
    crew_builder = MycrewCrew()
    return crew_builder.crew()


def _upload_to_snack(app_dir: Path) -> None:
    script_path = REPO_ROOT / "upload-to-snack.js"
    result = subprocess.run(["node", str(script_path), str(app_dir)], capture_output=True, text=True, check=False, timeout=120)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Snack upload failed").strip())
    print(result.stdout.strip())


def run(content_prompt: str = "Create a simple single-page app", upload_snack: bool = True) -> str:
    load_dotenv(override=True)

    print("🎯 Generating MVP: MyApp")
    print(f"📂 Output folder: {GENERATED_APP_DIR}\n")

    if not _copy_template():
        print("❌ Failed to copy template. Aborting.")
        return "copy_failed"

    print("🚀 Running planner / architect / coder crew...")
    crew = _build_crew()
    crew.kickoff(inputs={"content_prompt": content_prompt})

    if upload_snack:
        print("\n📦 Uploading generated app to Snack...")
        _upload_to_snack(GENERATED_APP_DIR)

    print("\n✅ MVP app generation complete!")
    return "crew_completed"


if __name__ == "__main__":
    run()
