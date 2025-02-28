import docker
from loguru import logger
from pathlib import Path
from typing import Dict, List, Optional, Any, Literal
import time
from docker.errors import APIError, ImageNotFound
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
    
    # Language-specific execution commands
    LANGUAGE_EXECUTORS = {
        "py": ["python", "-c"],
        "r": ["Rscript", "-e"],
    }
    
    # Language-specific messages
    LANGUAGE_SPECIFIC_MESSAGES = {
        "py": {
            "empty_output": "Empty. Make sure to explicitly print() the results in Python"
        },
        "r": {
            "empty_output": "Empty. Make sure to use print() or cat() to display results in R"
        }
    }

    def __init__(self):
        self._container_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_CONTAINERS)
        self._active_containers: Dict[str, ContainerMetrics] = {}
        self._lock = asyncio.Lock()
        self._docker = None  # Will be initialized in initialize()
        self._image_pull_locks: Dict[str, asyncio.Lock] = {}

    async def initialize(self):
        """Initialize the Docker client."""
        try:
            if self._docker is None:
                self._docker = aiodocker.Docker()
            else:
                # Check if the client is still valid
                if not await self._validate_docker_connection():
                    # Reinitialize if there was an error
                    await self.close()
                    self._docker = aiodocker.Docker()

            logger.info("Docker client initialized successfully")
            return self
        except Exception as e:
            logger.error(f"Error initializing Docker client: {str(e)}")
            raise

    async def close(self):
        """Close the Docker client."""
        if self._docker is not None:
            await self._docker.close()
            self._docker = None

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
        self,
        code: str,
        session_id: str,
        lang: Literal["py", "r"],
        files: Optional[List[Dict[str, Any]]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Execute code in a Docker container with file management."""
        container = None

        try:
            # Ensure Docker client is initialized and valid
            if self._docker is None:
                await self.initialize()
            else:
                # Verify Docker client is still valid
                if not await self._validate_docker_connection():
                    logger.warning("Docker client validation failed, reinitializing")
                    await self.close()
                    await self.initialize()

            # Create session directory before anything else
            session_path: Path = UPLOAD_PATH / session_id
            logger.info(f"Session path: {session_path}")
            session_path.mkdir(parents=True, exist_ok=True)
            # Log debug information
            logger.info(f"Session directory: {session_path}")
            logger.info(f"Session directory contents: {list(session_path.glob('*'))}")
            logger.info(f"Code to execute: {code}")

            async with self._container_semaphore:
                try:
                    # Ensure the image is available
                    image_name = settings.LANGUAGE_CONTAINERS.get(lang)
                    logger.info(f"Using container image: {image_name}")

                    try:
                        # Check if image exists
                        await self._docker.images.inspect(image_name)
                        logger.info(f"Image {image_name} is available")
                    except Exception as e:
                        # Check if it's a 404 error (image not found)
                        if isinstance(e, aiodocker.exceptions.DockerError) and e.status == 404:
                            # Get or create a lock for this specific image
                            if image_name not in self._image_pull_locks:
                                self._image_pull_locks[image_name] = asyncio.Lock()

                            # Acquire the lock for this image to prevent multiple pulls
                            async with self._image_pull_locks[image_name]:
                                # Check again if the image exists (another request might have pulled it while we were waiting)
                                try:
                                    await self._docker.images.inspect(image_name)
                                    logger.info(f"Image {image_name} is now available (pulled by another request)")
                                except Exception as check_again_error:
                                    if (
                                        isinstance(check_again_error, aiodocker.exceptions.DockerError)
                                        and check_again_error.status == 404
                                    ):
                                        # Pull the image if not available
                                        logger.info(f"Image {image_name} not found, pulling...")
                                        try:
                                            # Pull using aiodocker
                                            await self._docker.images.pull(image_name)
                                            logger.info(f"Successfully pulled image {image_name}")
                                        except Exception as pull_error:
                                            logger.error(f"Failed to pull image: {str(pull_error)}")
                                            return {
                                                "stdout": "",
                                                "stderr": f"Failed to pull required Docker image: {image_name}. Error: {str(pull_error)}",
                                                "status": "error",
                                                "files": [],
                                            }
                                    else:
                                        # Re-raise if it's not a 404 error
                                        logger.error(f"Error checking for image {image_name}: {str(check_again_error)}")
                                        raise
                        else:
                            # Re-raise if it's not a 404 error
                            logger.error(f"Error checking for image {image_name}: {str(e)}")
                            raise

                    # Create container config
                    config = {
                        "Image": image_name,
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

                    # Execute the code with the appropriate interpreter
                    logger.info(f"Code to execute: {code}")
                    logger.info(f"Language: {lang}")
                    
                    # Get the execution command for the specified language
                    exec_cmd = self.LANGUAGE_EXECUTORS.get(lang, self.LANGUAGE_EXECUTORS["py"])
                    logger.info(f"Using execution command: {exec_cmd}")
                    
                    # Execute the code with the appropriate interpreter
                    exec = await container.exec(cmd=[*exec_cmd, code], user="jovyan", stdout=True, stderr=True)
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

        except Exception as e:
            logger.error(f"Error in docker execution: {str(e)}")
            return {
                "stdout": "",
                "stderr": "Failed to execute code. Please try again.",
                "status": "error",
                "files": [],
            }

    async def get_active_containers(self) -> List[Dict[str, Any]]:
        """Get information about currently running containers."""
        async with self._lock:
            return [
                {"container_id": container_id, "metrics": metrics.__dict__}
                for container_id, metrics in self._active_containers.items()
            ]

    async def _validate_docker_connection(self):
        """Validate that the Docker connection is working properly."""
        try:
            # Instead of using ping(), try to get the Docker version
            # which is a simple API call that should work if the connection is valid
            await self._docker.version()
            logger.debug("Docker connection validated")
            return True
        except Exception as e:
            logger.warning(f"Docker connection validation failed: {str(e)}")
            return False


# Create singleton instance
docker_executor = DockerExecutor()
