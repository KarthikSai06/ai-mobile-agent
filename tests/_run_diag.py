"""Small diagnostic — run outcome/loop tests with verbose traceback captured."""
import subprocess, sys, os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

result = subprocess.run(
    [sys.executable, "-m", "pytest",
     "tests/test_agent_fixes.py::TestOutcomeTracking",
     "tests/test_agent_fixes.py::TestLoopDetector",
     "--tb=long", "-s"],
    cwd=PROJECT_ROOT,
    capture_output=True, text=True
)
print(result.stdout[-5000:])
print(result.stderr[-2000:])
