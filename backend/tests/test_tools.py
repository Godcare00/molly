import pytest
import tempfile
import os
from pathlib import Path

from app.tools.registry import registry, RiskLevel
from app.tools.system import GetSystemInfoTool, GetDiskUsageTool, GetMemoryUsageTool
from app.tools.filesystem import ListDirectoryTool, ReadFileTool, WriteFileTool, EditFileTool
from app.tools.terminal import ExecuteCommandTool
from app.tools.git import GitStatusTool, GitDiffTool, GitLogTool
from app.tools.projects import ListProjectsTool, GetProjectContextTool


class TestSystemTools:
    @pytest.mark.asyncio
    async def test_get_system_info(self):
        tool = GetSystemInfoTool()
        result = await tool.execute()
        assert result.success
        assert "os" in result.output
        assert "hostname" in result.output
        assert "python_version" in result.output

    @pytest.mark.asyncio
    async def test_get_disk_usage(self):
        tool = GetDiskUsageTool()
        result = await tool.execute()
        assert result.success
        assert "filesystems" in result.output
        assert len(result.output["filesystems"]) > 0

    @pytest.mark.asyncio
    async def test_get_memory_usage(self):
        tool = GetMemoryUsageTool()
        result = await tool.execute()
        assert result.success
        assert "ram" in result.output
        assert "swap" in result.output


class TestFilesystemTools:
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    @pytest.mark.asyncio
    async def test_list_directory(self, temp_dir):
        # Create test files
        (temp_dir / "file1.txt").write_text("content1")
        (temp_dir / "file2.txt").write_text("content2")
        (temp_dir / "subdir").mkdir()

        tool = ListDirectoryTool()
        result = await tool.execute(str(temp_dir))
        assert result.success
        assert len(result.output["entries"]) == 3
        names = [e["name"] for e in result.output["entries"]]
        assert "file1.txt" in names
        assert "file2.txt" in names
        assert "subdir" in names

    @pytest.mark.asyncio
    async def test_read_file(self, temp_dir):
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5")

        tool = ReadFileTool()
        result = await tool.execute(str(test_file))
        assert result.success
        assert "line1" in result.output["content"]
        assert result.output["total_lines"] == 5

    @pytest.mark.asyncio
    async def test_read_file_line_range(self, temp_dir):
        test_file = temp_dir / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5")

        tool = ReadFileTool()
        result = await tool.execute(str(test_file), start_line=2, end_line=4)
        assert result.success
        assert "line2" in result.output["content"]
        assert "line3" in result.output["content"]
        assert "line4" in result.output["content"]
        assert "line1" not in result.output["content"]
        assert "line5" not in result.output["content"]

    @pytest.mark.asyncio
    async def test_read_file_zip_lists_entries(self, temp_dir):
        import zipfile

        zip_path = temp_dir / "archive.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("hello.txt", "hello from inside the zip")
            zf.writestr("nested/data.json", '{"ok": true}')

        tool = ReadFileTool()
        result = await tool.execute(str(zip_path))
        assert result.success
        assert result.output["kind"] == "archive"
        names = [e["name"] for e in result.output["entries"]]
        assert "hello.txt" in names
        assert "nested/data.json" in names

    @pytest.mark.asyncio
    async def test_read_file_zip_entry_content(self, temp_dir):
        import zipfile

        zip_path = temp_dir / "archive.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("hello.txt", "hello from inside the zip")

        tool = ReadFileTool()
        result = await tool.execute(str(zip_path), archive_entry="hello.txt")
        assert result.success
        assert result.output["kind"] == "archive_entry"
        assert "hello from inside the zip" in result.output["content"]

    @pytest.mark.asyncio
    async def test_read_file_binary_summary(self, temp_dir):
        bin_path = temp_dir / "data.bin"
        bin_path.write_bytes(b"\x00\x01\x02\xffnot text")

        tool = ReadFileTool()
        result = await tool.execute(str(bin_path))
        assert result.success
        assert result.output["kind"] == "binary"
        assert "hex_preview" in result.output

    @pytest.mark.asyncio
    async def test_write_file(self, temp_dir):
        tool = WriteFileTool()
        result = await tool.execute(str(temp_dir / "new.txt"), "Hello World")
        assert result.success
        assert (temp_dir / "new.txt").read_text() == "Hello World"

    @pytest.mark.asyncio
    async def test_edit_file_replace(self, temp_dir):
        test_file = temp_dir / "edit.txt"
        test_file.write_text("old content")

        tool = EditFileTool()
        result = await tool.execute(str(test_file), "replace", old_text="old", new_text="new")
        assert result.success
        assert test_file.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_edit_file_insert(self, temp_dir):
        test_file = temp_dir / "edit.txt"
        test_file.write_text("line1\nline3")

        tool = EditFileTool()
        result = await tool.execute(str(test_file), "insert", line_number=2, new_text="line2")
        assert result.success
        content = test_file.read_text()
        assert "line1" in content
        assert "line2" in content
        assert "line3" in content


class TestTerminalTool:
    @pytest.mark.asyncio
    async def test_execute_command_simple(self):
        tool = ExecuteCommandTool()
        result = await tool.execute("echo hello")
        assert result.success
        assert "hello" in result.output["stdout"]

    @pytest.mark.asyncio
    async def test_execute_command_with_cwd(self, temp_dir):
        tool = ExecuteCommandTool()
        result = await tool.execute("pwd", cwd=str(temp_dir))
        assert result.success
        assert str(temp_dir) in result.output["stdout"]

    @pytest.mark.asyncio
    async def test_execute_command_failure(self):
        tool = ExecuteCommandTool()
        result = await tool.execute("exit 1")
        assert not result.success
        assert result.output["return_code"] != 0


class TestGitTools:
    @pytest.fixture
    def git_repo(self, temp_dir):
        import subprocess
        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=temp_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_dir, capture_output=True)
        (temp_dir / "file.txt").write_text("content")
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=temp_dir, capture_output=True)
        return temp_dir

    @pytest.mark.asyncio
    async def test_git_status(self, git_repo):
        tool = GitStatusTool()
        result = await tool.execute(str(git_repo))
        assert result.success
        assert "branch" in result.output

    @pytest.mark.asyncio
    async def test_git_log(self, git_repo):
        tool = GitLogTool()
        result = await tool.execute(str(git_repo), limit=5)
        assert result.success
        assert len(result.output["commits"]) > 0


class TestProjectTools:
    @pytest.mark.asyncio
    async def test_list_projects(self):
        tool = ListProjectsTool()
        result = await tool.execute()
        assert result.success
        assert "projects" in result.output

    @pytest.mark.asyncio
    async def test_get_project_context(self):
        tool = GetProjectContextTool()
        result = await tool.execute("mantis")
        # May not exist in test DB
        if result.success:
            assert "id" in result.output


class TestToolRegistry:
    def test_all_tools_registered(self):
        expected_tools = [
            "get_system_info",
            "get_disk_usage",
            "get_memory_usage",
            "get_processes",
            "get_service_status",
            "list_directory",
            "search_files",
            "read_file",
            "write_file",
            "edit_file",
            "execute_command",
            "git_status",
            "git_diff",
            "git_log",
            "list_projects",
            "get_project_context",
            "view_image",
        ]
        for tool_name in expected_tools:
            assert tool_name in registry.list_tools(), f"Missing tool: {tool_name}"

    def test_tool_schemas_generated(self):
        for tool_name in registry.list_tools():
            schema = registry.get_schema(tool_name)
            assert schema is not None
            assert schema.name == tool_name
            openai_schema = schema.to_openai_schema()
            assert openai_schema["type"] == "function"
            assert "name" in openai_schema["function"]
            assert "parameters" in openai_schema["function"]