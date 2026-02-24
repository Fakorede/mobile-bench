# Copyright (c) 2024 Bytedance Ltd. and/or its affiliates

#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at

#      http://www.apache.org/licenses/LICENSE-2.0

#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import logging
from pathlib import Path
from typing import Optional, Union

import docker

# Increase timeout for long-running operations (e.g., large image pulls, slow builds)
# Default is 60s which can cause timeouts for Android builds and large image pulls
docker_client = docker.from_env(timeout=600)


def exists(image_name: str) -> bool:
    try:
        docker_client.images.get(image_name)
        return True
    except docker.errors.ImageNotFound:
        return False


def pull(image_name: str, ghcr_username: str, logger: logging.Logger) -> bool:
    """
    Pull a Docker image from GHCR and tag it with local name.

    Args:
        image_name: Local image name (e.g., mobiledevbench/org_mb_repo:pr-123)
        ghcr_username: GHCR username/organization
        logger: Logger instance

    Returns:
        bool: True if pull and tag successful, False otherwise
    """
    # Extract tag and repo from local image (mobiledevbench/repo:tag)
    tag = image_name.split(":")[-1] if ":" in image_name else "latest"
    repo_name = image_name.split(":")[0] if ":" in image_name else image_name

    # GHCR format: ghcr.io/username/mobiledevbench/repo:tag
    ghcr_image = f"ghcr.io/{ghcr_username}/{repo_name}:{tag}"

    logger.info(f"Pulling image from GHCR: {ghcr_image}")

    try:
        # Pull the image from GHCR
        pull_logs = docker_client.api.pull(ghcr_image, stream=True, decode=True)
        for log in pull_logs:
            if "status" in log:
                logger.debug(f"{log['status']} {log.get('progress', '')}".strip())
            elif "error" in log:
                error_message = log["error"].strip()
                logger.error(f"Docker pull error: {error_message}")
                return False

        logger.info(f"Successfully pulled: {ghcr_image}")

        # Tag with local name
        logger.info(f"Tagging as: {image_name}")
        image = docker_client.images.get(ghcr_image)
        image.tag(image_name)
        logger.info(f"Successfully tagged as: {image_name}")

        # Remove the GHCR remote tag to save space
        logger.debug(f"Removing remote tag: {ghcr_image}")
        docker_client.images.remove(ghcr_image, force=False)

        return True

    except docker.errors.APIError as e:
        logger.error(f"Pull error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unknown pull error occurred: {e}")
        return False


def delete(image_name: str, logger: logging.Logger, force: bool = True) -> bool:
    """
    Delete a Docker image to free up disk space.

    Args:
        image_name: Image name to delete
        logger: Logger instance
        force: Force removal even if image is in use

    Returns:
        bool: True if deletion successful, False otherwise
    """
    logger.info(f"Deleting image: {image_name}")
    try:
        docker_client.images.remove(image_name, force=force)
        logger.info(f"Successfully deleted image: {image_name}")
        return True
    except docker.errors.ImageNotFound:
        logger.warning(f"Image not found, cannot delete: {image_name}")
        return False
    except docker.errors.APIError as e:
        logger.error(f"Delete error: {e}")
        return False
    except Exception as e:
        logger.error(f"Unknown delete error occurred: {e}")
        return False


def build(
    workdir: Path, dockerfile_name: str, image_full_name: str, logger: logging.Logger
):
    workdir = str(workdir)
    logger.info(
        f"Start building image `{image_full_name}`, working directory is `{workdir}`"
    )
    try:
        build_logs = docker_client.api.build(
            path=workdir,
            dockerfile=dockerfile_name,
            tag=image_full_name,
            rm=True,
            forcerm=True,
            decode=True,
            encoding="utf-8",
        )

        for log in build_logs:
            if "stream" in log:
                logger.info(log["stream"].strip())
            elif "error" in log:
                error_message = log["error"].strip()
                logger.error(f"Docker build error: {error_message}")
                raise RuntimeError(f"Docker build failed: {error_message}")
            elif "status" in log:
                logger.info(log["status"].strip())
            elif "aux" in log:
                logger.info(log["aux"].get("ID", "").strip())

        logger.info(f"image({workdir}) build success: {image_full_name}")
    except docker.errors.BuildError as e:
        logger.error(f"build error: {e}")
        raise e
    except Exception as e:
        logger.error(f"Unknown build error occurred: {e}")
        raise e


def cleanup_containers(logger: logging.Logger, status_filter: str = "exited") -> int:
    """
    Clean up stopped/exited Docker containers to free up disk space.

    Args:
        logger: Logger instance
        status_filter: Container status to filter (default: "exited")
                      Options: "exited", "dead", "created"

    Returns:
        int: Number of containers removed
    """
    try:
        containers = docker_client.containers.list(
            all=True, filters={"status": status_filter}
        )
        removed_count = 0

        for container in containers:
            try:
                logger.debug(f"Removing container: {container.id[:12]} ({container.name})")
                container.remove(force=True)
                removed_count += 1
            except docker.errors.NotFound:
                # Container already removed, skip
                logger.debug(f"Container {container.id[:12]} already removed")
            except docker.errors.APIError as e:
                # Handle API errors (timeouts, connection issues) gracefully
                logger.warning(f"Failed to remove container {container.id[:12]}: {e}")
            except Exception as e:
                logger.warning(f"Unexpected error removing container {container.id[:12]}: {e}")

        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} {status_filter} containers")
        return removed_count

    except docker.errors.APIError as e:
        logger.error(f"Docker API error during cleanup: {e}")
        return 0
    except Exception as e:
        logger.error(f"Failed to cleanup containers: {e}")
        return 0


def run(
    image_full_name: str,
    run_command: str,
    output_path: Optional[Path] = None,
    global_env: Optional[list[str]] = None,
    volumes: Optional[Union[dict[str, str], list[str]]] = None,
    timeout: int = 3600,  # 1 hour default timeout for container execution
) -> str:
    container = None
    try:
        container = docker_client.containers.run(
            image=image_full_name,
            command=run_command,
            remove=False,
            detach=True,
            stdout=True,
            stderr=True,
            environment=global_env,
            volumes=volumes,
        )

        output = ""
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                try:
                    # Stream logs with timeout handling
                    for line in container.logs(stream=True, follow=True):
                        line_decoded = line.decode("utf-8")
                        f.write(line_decoded)
                        output += line_decoded
                except docker.errors.APIError as e:
                    # Handle connection/timeout errors gracefully
                    print(f"Warning: Log streaming interrupted: {e}")
                    # Try to get remaining logs
                    try:
                        container.reload()
                        remaining = container.logs(tail=100).decode("utf-8")
                        f.write(f"\n[Log streaming interrupted, last 100 lines:]\n{remaining}")
                        output += remaining
                    except:
                        pass
        else:
            # Wait for container with timeout
            try:
                container.wait(timeout=timeout)
                output = container.logs().decode("utf-8")
            except docker.errors.APIError as e:
                print(f"Warning: Container wait timeout: {e}")
                # Try to get partial output
                try:
                    output = container.logs().decode("utf-8")
                except:
                    output = f"Error: Container execution timeout after {timeout}s"

        return output
    finally:
        if container:
            try:
                # Ensure container is stopped before removing
                try:
                    container.reload()
                    if container.status in ["running", "created"]:
                        container.stop(timeout=10)
                except:
                    pass
                container.remove(force=True)
            except Exception as e:
                print(f"Warning: Failed to remove container: {e}")
