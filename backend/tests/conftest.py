import pytest
import tempfile
import os
from pathlib import Path

# Set test environment before importing app
os.environ["LLM_PROVIDER"] = "openai"
os.environ["LLM_BASE_URL"] = "https://api.openai.com/v1"
os.environ["LLM_API_KEY"] = "test-key"
os.environ["LLM_MODEL"] = "gpt-4o"
os.environ["DATABASE_PATH"] = ":memory:"
os.environ["UPLOADS_DIR"] = "/tmp/molly_test_uploads"
os.environ["PROJECTS_DIR"] = "/tmp/molly_test_projects"
os.environ["MAX_IMAGE_SIZE_MB"] = "1"
os.environ["MAX_UPLOAD_SIZE_MB"] = "5"
os.environ["MAX_ITERATIONS"] = "10"
os.environ["MAX_TOOL_CALLS"] = "20"
os.environ["MAX_EXECUTION_TIME_SECONDS"] = "60"
os.environ["MAX_COMMAND_TIMEOUT_SECONDS"] = "10"
os.environ["MAX_CONTEXT_TOKENS"] = "4000"
os.environ["MAX_TOOL_OUTPUT_CHARS"] = "1000"
os.environ["APPROVAL_TIMEOUT_MINUTES"] = "1"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["LOG_LEVEL"] = "DEBUG"


@pytest.fixture(scope="session", autouse=True)
def setup_test_dirs():
    """Create test directories."""
    Path("/tmp/molly_test_uploads").mkdir(parents=True, exist_ok=True)
    Path("/tmp/molly_test_projects").mkdir(parents=True, exist_ok=True)
    yield
    # Cleanup
    import shutil
    shutil.rmtree("/tmp/molly_test_uploads", ignore_errors=True)
    shutil.rmtree("/tmp/molly_test_projects", ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_db():
    """Reset database before each test."""
    from app.storage.database import init_db, close_db
    close_db()
    init_db()
    yield
    close_db()


@pytest.fixture
def temp_dir():
    """Provide a temporary directory."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def conversation_id():
    """Create a test conversation and return its ID."""
    from app.storage.conversations import create_conversation
    conv = create_conversation("Test Conversation")
    return conv.id


@pytest.fixture
def task_id(conversation_id):
    """Create a test task and return its ID."""
    from app.agent.tasks import create_task
    task = create_task(conversation_id)
    return task.task_id