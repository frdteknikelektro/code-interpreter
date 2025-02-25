import docker
from loguru import logger
from pathlib import Path
from typing import Dict, List, Optional, Any
import time
from docker.errors import APIError
import asyncio
import contextlib
import fcntl
from dataclasses import dataclass
from datetime import datetime
import hashlib
import mimetypes
from app.shared.const import UPLOAD_PATH
from app.utils.generate_id import generate_id
import aiodocker
import json

from ..shared.config import get_settings
from .database import db_manager

settings = get_settings()


@dataclass
class ContainerMetrics:
    start_time: datetime
    container_id: str
    memory_usage: int = 0
    cpu_usage: float = 0.0


class DockerExecutor:
    """Executes code in Docker containers with file management."""

    WORK_DIR = "/mnt/data"  # Working directory will be the same as data mount point
    DATA_MOUNT = "/mnt/data"  # Mount point for session data
    MAX_CONCURRENT_CONTAINERS = 10

    def __init__(self):
        self._container_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_CONTAINERS)
        self._active_containers: Dict[str, ContainerMetrics] = {}
        self._lock = asyncio.Lock()
        self._docker = None  # Will be initialized in execute()

    @contextlib.contextmanager
    def _file_lock(self, path: Path):
        """Provide file-based locking for concurrent operations."""
        lock_path = path.parent / f"{path.name}.lock"
        lock_file = open(lock_path, "w+")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
            lock_path.unlink(missing_ok=True)

    async def _update_container_metrics(self, container) -> None:
        """Update metrics for a running container."""
        try:
            stats_data = await container.stats(stream=False)

            # Handle empty stats data
            if not stats_data:
                logger.warning(f"No stats data available for container {container.id}")
                return

            # aiodocker returns stats data differently, handle it appropriately
            stats = stats_data[0] if isinstance(stats_data, list) and stats_data else stats_data
            if not stats:
                logger.warning(f"No stats available for container {container.id}")
                return

            # Calculate memory usage - handle both possible formats
            memory_usage = 0
            if isinstance(stats, dict):
                memory_stats = stats.get("memory_stats", {})
                memory_usage = memory_stats.get("usage", 0)
            elif isinstance(stats, bytes):
                # If stats is returned as bytes, decode it
                try:
                    stats = json.loads(stats.decode())
                    memory_stats = stats.get("memory_stats", {})
                    memory_usage = memory_stats.get("usage", 0)
                except json.JSONDecodeError:
                    logger.warning(f"Could not decode stats for container {container.id}")
                    return

            # Calculate CPU usage
            cpu_stats = stats.get("cpu_stats", {})
            precpu_stats = stats.get("precpu_stats", {})

            cpu_usage_stats = cpu_stats.get("cpu_usage", {})
            precpu_usage_stats = precpu_stats.get("cpu_usage", {})

            cpu_delta = cpu_usage_stats.get("total_usage", 0) - precpu_usage_stats.get("total_usage", 0)
            system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get("system_cpu_usage", 0)

            cpu_usage = (cpu_delta / system_delta) * 100.0 if system_delta > 0 else 0.0

            logger.info(f"Container {container.id} memory usage: {memory_usage}, CPU usage: {cpu_usage}")

            async with self._lock:
                if container.id in self._active_containers:
                    self._active_containers[container.id].memory_usage = memory_usage
                    self._active_containers[container.id].cpu_usage = cpu_usage
        except Exception as e:
            logger.error(f"Error updating metrics for container {container.id}: {str(e)}")

    def _clean_output(self, raw_output: bytes) -> str:
        """Clean Docker multiplexed output format."""
        # Skip the first 8 bytes of each frame (header) and combine the rest
        output_parts = []
        i = 0
        while i < len(raw_output):
            # Each frame starts with 8 bytes of header
            if i + 8 > len(raw_output):
                break
            # The fourth byte indicates the stream (1 = stdout, 2 = stderr)
            # The next 4 bytes contain the size of the frame
            frame_size = int.from_bytes(raw_output[i + 4 : i + 8], byteorder="big")
            # Extract the frame content
            if i + 8 + frame_size > len(raw_output):
                break
            frame_data = raw_output[i + 8 : i + 8 + frame_size]
            output_parts.append(frame_data)
            i += 8 + frame_size

        return b"".join(output_parts).decode("utf-8").strip()

    async def execute(
        self, code: str, session_id: str, files: Optional[List[Dict[str, Any]]] = None, timeout: int = 30
    ) -> Dict[str, Any]:
        """Execute code in a Docker container with file management."""
        container = None

        if self._docker is None:
            self._docker = aiodocker.Docker()

        # Create session directory before anything else
        session_path: Path = UPLOAD_PATH / session_id
        logger.info(f"Session path: {session_path}")
        session_path.mkdir(parents=True, exist_ok=True)
        # Log debug information
        logger.info(f"Session directory: {session_path}")
        logger.info(f"Session directory contents: {list(session_path.glob('*'))}")
        logger.info(f"Code to execute: {code}")

        async with self._container_semaphore:  # Limit concurrent containers
            try:
                # Create container config
                config = {
                    "Image": "jupyter/scipy-notebook:latest",
                    "Cmd": ["sleep", "infinity"],
                    "WorkingDir": self.WORK_DIR,
                    "NetworkDisabled": True,
                    "HostConfig": {
                        "Memory": 512 * 1024 * 1024,  # 512MB in bytes
                        "Mounts": [
                            {
                                "Type": "bind",
                                "Source": str(settings.HOST_FILE_UPLOAD_PATH_ABS / session_id),
                                "Target": self.DATA_MOUNT,
                            }
                        ],
                    },
                }

                # Create and start container
                container = await self._docker.containers.create(config=config)
                await container.start()

                # Track container metrics
                async with self._lock:
                    self._active_containers[container.id] = ContainerMetrics(
                        start_time=datetime.now(), container_id=container.id
                    )

                # Start metrics monitoring
                asyncio.create_task(self._update_container_metrics(container))

                # Wait for container to be running
                start_time = time.time()
                while True:
                    info = await container.show()
                    if info["State"]["Running"]:
                        break
                    if time.time() - start_time > 10:
                        raise RuntimeError("Container failed to start properly")
                    await asyncio.sleep(0.1)

                # Fix permissions for mounted directory
                exec = await container.exec(
                    cmd=["chown", "-R", "jovyan:users", self.DATA_MOUNT], user="root", stdout=True, stderr=True
                )
                # Use raw API call to get output
                exec_url = f"exec/{exec._id}/start"
                async with self._docker._query(
                    exec_url,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps({"Detach": False, "Tty": False}),
                ) as response:
                    output = await response.read()
                    output_text = self._clean_output(output)

                # Execute the Python code as jovyan user
                exec = await container.exec(cmd=["python", "-c", code], user="jovyan", stdout=True, stderr=True)
                # Use raw API call to get output
                exec_url = f"exec/{exec._id}/start"
                async with self._docker._query(
                    exec_url,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                    data=json.dumps({"Detach": False, "Tty": False}),
                ) as response:
                    output = await response.read()
                    output_text = self._clean_output(output)

                # Check execution status
                exec_inspect = await exec.inspect()
                if exec_inspect["ExitCode"] != 0:
                    return {"stdout": "", "stderr": output_text, "status": "error", "files": []}

                # List files in the session directory
                output_files = []
                existing_filenames = {file["name"] for file in (files or [])}
                logger.info(f"Existing filenames: {existing_filenames}")
                logger.info(f"Scanning directory {session_path} for created files")
                for file_path in session_path.glob("*"):
                    if file_path.is_file() and file_path.name not in existing_filenames:
                        file_id = generate_id()
                        file_size = file_path.stat().st_size
                        logger.info(f"Found new file: {file_path}, size: {file_size}")

                        # Calculate file metadata
                        content_type, _ = mimetypes.guess_type(file_path.name) or ("application/octet-stream", None)
                        etag = hashlib.md5(str(file_path.stat().st_mtime).encode()).hexdigest()

                        # Prepare file data for database
                        file_data = {
                            "id": file_id,
                            "session_id": session_id,
                            "filename": file_path.name,
                            "filepath": session_id + "/" + file_path.name,
                            "size": file_size,
                            "content_type": content_type,
                            "original_filename": file_path.name,
                            "etag": etag,
                            "name": f"{session_id}/{file_id}/{file_path.name}",
                        }
                        logger.info(f"Saving file metadata to database: {file_data}")

                        # Save to database
                        await db_manager.add_file(file_data)
                        output_files.append(file_data)

                return {
                    "stdout": output_text,
                    "stderr": "",
                    "status": "ok",
                    "files": output_files,
                    "metrics": {
                        "memory_usage": self._active_containers[container.id].memory_usage,
                        "cpu_usage": self._active_containers[container.id].cpu_usage,
                        "execution_time": (
                            datetime.now() - self._active_containers[container.id].start_time
                        ).total_seconds(),
                    },
                }

            except Exception as e:
                logger.error(f"Error in docker execution: {str(e)}")
                return {
                    "stdout": "",
                    "stderr": "Failed to execute code. Please try again.",
                    "status": "error",
                    "files": [],
                }

            finally:
                # Cleanup container and metrics
                if container:
                    try:
                        await container.delete(force=True)
                        async with self._lock:
                            self._active_containers.pop(container.id, None)
                    except Exception as e:
                        logger.error(f"Error removing container: {str(e)}")

    async def get_active_containers(self) -> List[Dict[str, Any]]:
        """Get information about currently running containers."""
        async with self._lock:
            return [
                {"container_id": container_id, "metrics": metrics.__dict__}
                for container_id, metrics in self._active_containers.items()
            ]


# Create singleton instance
docker_executor = DockerExecutor()
