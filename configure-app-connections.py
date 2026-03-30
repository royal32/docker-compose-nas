#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
import shlex
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request


ROOT_DIR = Path(__file__).resolve().parent
SSL_CONTEXT = ssl._create_unverified_context()


@dataclass(frozen=True)
class ArrService:
    service_name: str
    display_name: str
    url_base: str
    api_key_env: str
    root_folder_env: str
    category_env: str
    download_path_env: str
    qbit_implementation_field: str
    qbit_directory_field: str | None
    prowlarr_implementation: str
    internal_base_url: str


ARR_SERVICES: tuple[ArrService, ...] = (
    ArrService(
        service_name="sonarr",
        display_name="Sonarr",
        url_base="/sonarr",
        api_key_env="SONARR_API_KEY",
        root_folder_env="SONARR_ROOT_FOLDER",
        category_env="SONARR_QBIT_CATEGORY",
        download_path_env="SONARR_DOWNLOAD_PATH",
        qbit_implementation_field="tvCategory",
        qbit_directory_field=None,
        prowlarr_implementation="Sonarr",
        internal_base_url="http://sonarr:8989/sonarr",
    ),
    ArrService(
        service_name="radarr",
        display_name="Radarr",
        url_base="/radarr",
        api_key_env="RADARR_API_KEY",
        root_folder_env="RADARR_ROOT_FOLDER",
        category_env="RADARR_QBIT_CATEGORY",
        download_path_env="RADARR_DOWNLOAD_PATH",
        qbit_implementation_field="movieCategory",
        qbit_directory_field=None,
        prowlarr_implementation="Radarr",
        internal_base_url="http://radarr:7878/radarr",
    ),
    ArrService(
        service_name="lidarr",
        display_name="Lidarr",
        url_base="/lidarr",
        api_key_env="LIDARR_API_KEY",
        root_folder_env="LIDARR_ROOT_FOLDER",
        category_env="LIDARR_QBIT_CATEGORY",
        download_path_env="LIDARR_DOWNLOAD_PATH",
        qbit_implementation_field="category",
        qbit_directory_field="directory",
        prowlarr_implementation="Lidarr",
        internal_base_url="http://lidarr:8686/lidarr",
    ),
)


def log(message: str) -> None:
    print(f"[connections] {message}")


def parse_env_file(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        values[key] = value

    return values


def run_compose(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT_DIR,
        check=check,
        capture_output=True,
        text=True,
    )


def compose_running_services() -> set[str]:
    result = run_compose(["ps", "--services", "--status", "running"])
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def exec_in_service(service: str, command: str, dry_run: bool) -> None:
    if dry_run:
        log(f"[dry-run] docker compose exec -T {service} sh -lc {command}")
        return

    run_compose(["exec", "-T", service, "sh", "-lc", command])


class JsonClient:
    def __init__(self, base_url: str, default_headers: dict[str, str] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Any | None = None,
        form_data: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        request_headers = dict(self.default_headers)
        data: bytes | None = None

        if payload is not None:
            request_headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        elif form_data is not None:
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = parse.urlencode(form_data).encode("utf-8")

        http_request = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )

        try:
            with request.urlopen(http_request, context=SSL_CONTEXT) as response:
                body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {body}") from exc

        if not expect_json:
            return body

        if not body.strip():
            return None

        return json.loads(body)


class ContainerJsonClient:
    def __init__(self, service: str, base_url: str, default_headers: dict[str, str] | None = None) -> None:
        self.service = service
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Any | None = None,
        form_data: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        command = [
            "exec",
            "-T",
            self.service,
            "curl",
            "-sS",
            "-o",
            "-",
            "-w",
            "\n__STATUS__:%{http_code}",
            "-X",
            method,
        ]

        for header_name, header_value in self.default_headers.items():
            command.extend(["-H", f"{header_name}: {header_value}"])

        if payload is not None:
            command.extend(["-H", "Content-Type: application/json", "--data", json.dumps(payload)])
        elif form_data is not None:
            command.extend(["-H", "Content-Type: application/x-www-form-urlencoded", "--data", parse.urlencode(form_data)])

        command.append(f"{self.base_url}{path}")

        last_error = ""
        for attempt in range(20):
            result = run_compose(command, check=False)
            output = result.stdout
            body, _, status_line = output.rpartition("\n__STATUS__:")
            status_code = status_line.strip()

            if result.returncode == 0 and status_code.isdigit() and 200 <= int(status_code) < 300:
                if not expect_json:
                    return body
                if not body.strip():
                    return None
                return json.loads(body)

            last_error = result.stderr.strip() or body or f"HTTP {status_code or 'unknown'}"
            if status_code in {"000", "502", "503", "504"} and attempt < 19:
                time.sleep(2)
                continue

            raise RuntimeError(f"{method} {path} failed: {last_error}")

        raise RuntimeError(f"{method} {path} failed: {last_error}")


class QBittorrentClient(JsonClient):
    def __init__(self, username: str, password: str) -> None:
        super().__init__("http://127.0.0.1:8080")
        self.username = username
        self.password = password
        self.cookie_file = "/tmp/qbit-cookies.txt"

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: Any | None = None,
        form_data: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        curl_parts = [
            "curl",
            "-s",
            "-X",
            shlex.quote(method),
            "-b",
            shlex.quote(self.cookie_file),
            "-c",
            shlex.quote(self.cookie_file),
        ]
        if payload is not None:
            curl_parts.extend([
                "-H",
                shlex.quote("Content-Type: application/json"),
                "--data",
                shlex.quote(json.dumps(payload)),
            ])
        elif form_data is not None:
            curl_parts.extend([
                "-H",
                shlex.quote("Content-Type: application/x-www-form-urlencoded"),
                "--data",
                shlex.quote(parse.urlencode(form_data)),
            ])

        curl_parts.append(shlex.quote(f"{self.base_url}{path}"))

        result = run_compose(
            ["exec", "-T", "qbittorrent", "sh", "-lc", " ".join(curl_parts)],
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"curl request failed for {method} {path}: {result.stderr.strip()}")

        body = result.stdout

        if not expect_json:
            return body

        if not body.strip():
            return None

        return json.loads(body)

    def login(self) -> None:
        last_response = ""
        for _ in range(20):
            try:
                response = self.request_json(
                    "POST",
                    "/api/v2/auth/login",
                    form_data={"username": self.username, "password": self.password},
                    expect_json=False,
                )
                last_response = response.strip()
                if last_response == "Ok.":
                    return
            except RuntimeError:
                pass

            time.sleep(2)

        raise RuntimeError(f"qBittorrent login failed: {last_response or 'service did not become ready in time'}")


class ArrApi:
    def __init__(self, service: ArrService, api_key: str) -> None:
        self.service = service
        service_port = {
            "sonarr": 8989,
            "radarr": 7878,
            "lidarr": 8686,
        }[service.service_name]
        self.client = ContainerJsonClient(
            service.service_name,
            f"http://127.0.0.1:{service_port}{service.url_base}",
            default_headers={"X-Api-Key": api_key},
        )

    def get_root_folders(self) -> list[dict[str, Any]]:
        return self.client.request_json("GET", "/api/v3/rootfolder") or []

    def create_root_folder(self, path: str) -> None:
        self.client.request_json("POST", "/api/v3/rootfolder", payload={"path": path})

    def get_download_clients(self) -> list[dict[str, Any]]:
        return self.client.request_json("GET", "/api/v3/downloadclient") or []

    def get_download_client_schema(self) -> list[dict[str, Any]]:
        return self.client.request_json("GET", "/api/v3/downloadclient/schema") or []

    def upsert_download_client(self, payload: dict[str, Any], item_id: int | None) -> None:
        if item_id is None:
            self.client.request_json("POST", "/api/v3/downloadclient", payload=payload)
            return

        self._try_put("/api/v3/downloadclient", item_id, payload)

    def _try_put(self, base_path: str, item_id: int, payload: dict[str, Any]) -> None:
        errors: list[str] = []

        for path in (f"{base_path}/{item_id}", base_path):
            try:
                self.client.request_json("PUT", path, payload=payload)
                return
            except RuntimeError as exc:
                errors.append(str(exc))

        raise RuntimeError("\n".join(errors))


class ProwlarrApi:
    def __init__(self, api_key: str) -> None:
        self.client = ContainerJsonClient(
            "prowlarr",
            "http://127.0.0.1:9696/prowlarr",
            default_headers={"X-Api-Key": api_key},
        )

    def get_applications(self) -> list[dict[str, Any]]:
        return self.client.request_json("GET", "/api/v1/applications") or []

    def get_schema(self) -> list[dict[str, Any]]:
        return self.client.request_json("GET", "/api/v1/applications/schema") or []

    def upsert_application(self, payload: dict[str, Any], item_id: int | None) -> None:
        if item_id is None:
            self.client.request_json("POST", "/api/v1/applications", payload=payload)
            return

        errors: list[str] = []
        for path in (f"/api/v1/applications/{item_id}", "/api/v1/applications"):
            try:
                self.client.request_json("PUT", path, payload=payload)
                return
            except RuntimeError as exc:
                errors.append(str(exc))

        raise RuntimeError("\n".join(errors))


def field_value_map(fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {field["name"]: field.get("value") for field in fields}


def apply_field_overrides(fields: list[dict[str, Any]], overrides: dict[str, Any]) -> list[dict[str, Any]]:
    patched_fields = copy.deepcopy(fields)
    for field in patched_fields:
        if field["name"] in overrides:
            field["value"] = overrides[field["name"]]
    return patched_fields


def schema_by_implementation(schema: list[dict[str, Any]], implementation: str) -> dict[str, Any]:
    for item in schema:
        if item.get("implementation") == implementation:
            return copy.deepcopy(item)

    raise RuntimeError(f"Schema for implementation {implementation} was not found")


def ensure_directory(service: str, path: str, dry_run: bool) -> None:
    command = f"mkdir -p {shlex.quote(path)} && chown -R abc:abc {shlex.quote(path)}"
    exec_in_service(service, command, dry_run)


def ensure_qbittorrent_paths_and_categories(env: dict[str, str], running_services: set[str], dry_run: bool) -> None:
    if "qbittorrent" not in running_services:
        log("Skipping qBittorrent automation because the service is not running")
        return

    ensure_directory("qbittorrent", env["QBITTORRENT_SAVE_PATH"], dry_run)
    ensure_directory("qbittorrent", env["QBITTORRENT_TEMP_PATH"], dry_run)

    for arr_service in ARR_SERVICES:
        if arr_service.service_name in running_services:
            ensure_directory("qbittorrent", env[arr_service.download_path_env], dry_run)

    if dry_run:
        log("[dry-run] Would update qBittorrent preferences and categories")
        return

    qbit = QBittorrentClient(env["QBITTORRENT_USERNAME"], env["QBITTORRENT_PASSWORD"])
    qbit.login()
    preferences = qbit.request_json("GET", "/api/v2/app/preferences")

    desired_preferences: dict[str, Any] = {}
    if preferences.get("save_path") != env["QBITTORRENT_SAVE_PATH"]:
        desired_preferences["save_path"] = env["QBITTORRENT_SAVE_PATH"]
    if preferences.get("temp_path") != env["QBITTORRENT_TEMP_PATH"]:
        desired_preferences["temp_path"] = env["QBITTORRENT_TEMP_PATH"]
    if preferences.get("temp_path_enabled") is not True:
        desired_preferences["temp_path_enabled"] = True

    if desired_preferences:
        qbit.request_json(
            "POST",
            "/api/v2/app/setPreferences",
            form_data={"json": json.dumps(desired_preferences)},
            expect_json=False,
        )
        log("Updated qBittorrent save-path preferences")
    else:
        log("qBittorrent save-path preferences already match the desired state")

    categories = qbit.request_json("GET", "/api/v2/torrents/categories") or {}
    for arr_service in ARR_SERVICES:
        if arr_service.service_name not in running_services:
            continue

        category_name = env[arr_service.category_env]
        save_path = env[arr_service.download_path_env]
        existing = categories.get(category_name)

        if existing is None:
            qbit.request_json(
                "POST",
                "/api/v2/torrents/createCategory",
                form_data={"category": category_name, "savePath": save_path},
                expect_json=False,
            )
            log(f"Created qBittorrent category {category_name}")
            continue

        if existing.get("savePath") != save_path:
            qbit.request_json(
                "POST",
                "/api/v2/torrents/editCategory",
                form_data={"category": category_name, "savePath": save_path},
                expect_json=False,
            )
            log(f"Updated qBittorrent category {category_name}")
        else:
            log(f"qBittorrent category {category_name} already matches the desired state")


def ensure_arr_root_folder(arr_api: ArrApi, env: dict[str, str], dry_run: bool) -> None:
    path = env[arr_api.service.root_folder_env]
    ensure_directory(arr_api.service.service_name, path, dry_run)

    if dry_run:
        log(f"[dry-run] Would ensure {arr_api.service.display_name} root folder {path}")
        return

    root_folders = arr_api.get_root_folders()
    if any(folder.get("path") == path for folder in root_folders):
        log(f"{arr_api.service.display_name} root folder already present: {path}")
        return

    arr_api.create_root_folder(path)
    log(f"Created {arr_api.service.display_name} root folder {path}")


def ensure_arr_download_client(arr_api: ArrApi, env: dict[str, str], dry_run: bool) -> None:
    schema = schema_by_implementation(arr_api.get_download_client_schema(), "QBittorrent")
    field_overrides = {
        "host": "vpn",
        "port": 8080,
        "useSsl": False,
        "urlBase": "",
        "username": env["QBITTORRENT_USERNAME"],
        "password": env["QBITTORRENT_PASSWORD"],
        arr_api.service.qbit_implementation_field: env[arr_api.service.category_env],
    }
    if arr_api.service.qbit_directory_field is not None:
        field_overrides[arr_api.service.qbit_directory_field] = env[arr_api.service.download_path_env]

    payload = {
        "name": "qBittorrent",
        "enable": True,
        "protocol": schema.get("protocol", "torrent"),
        "priority": schema.get("priority", 1),
        "removeCompletedDownloads": schema.get("removeCompletedDownloads", True),
        "removeFailedDownloads": schema.get("removeFailedDownloads", True),
        "implementationName": schema.get("implementationName", "qBittorrent"),
        "implementation": schema["implementation"],
        "configContract": schema["configContract"],
        "fields": apply_field_overrides(schema["fields"], field_overrides),
        "tags": schema.get("tags", []),
    }

    if dry_run:
        log(f"[dry-run] Would ensure {arr_api.service.display_name} qBittorrent download client")
        return

    existing_clients = arr_api.get_download_clients()
    existing = next(
        (
            client
            for client in existing_clients
            if client.get("implementation") == "QBittorrent" or client.get("name") == "qBittorrent"
        ),
        None,
    )

    if existing is not None:
        desired_values = field_value_map(payload["fields"])
        current_values = field_value_map(existing.get("fields", []))
        same_fields = True
        for field_name, desired_value in desired_values.items():
            if field_name == "password":
                continue
            if current_values.get(field_name) != desired_value:
                same_fields = False
                break

        if existing.get("enable") and same_fields:
            log(f"{arr_api.service.display_name} qBittorrent client already matches the desired state")
            return

        payload["id"] = existing["id"]
        arr_api.upsert_download_client(payload, existing["id"])
        log(f"Updated {arr_api.service.display_name} qBittorrent client")
        return

    arr_api.upsert_download_client(payload, None)
    log(f"Created {arr_api.service.display_name} qBittorrent client")


def ensure_prowlarr_application(
    prowlarr_api: ProwlarrApi,
    arr_service: ArrService,
    env: dict[str, str],
    dry_run: bool,
) -> None:
    schema = schema_by_implementation(prowlarr_api.get_schema(), arr_service.prowlarr_implementation)
    payload = {
        "name": arr_service.display_name,
        "enable": schema.get("enable", True),
        "syncLevel": schema.get("syncLevel", "fullSync"),
        "implementationName": schema.get("implementationName", arr_service.display_name),
        "implementation": schema["implementation"],
        "configContract": schema["configContract"],
        "fields": apply_field_overrides(
            schema["fields"],
            {
                "prowlarrUrl": "http://prowlarr:9696/prowlarr",
                "baseUrl": arr_service.internal_base_url,
                "apiKey": env[arr_service.api_key_env],
            },
        ),
        "tags": schema.get("tags", []),
    }

    if dry_run:
        log(f"[dry-run] Would ensure Prowlarr application link for {arr_service.display_name}")
        return

    existing_apps = prowlarr_api.get_applications()
    existing = next(
        (
            app
            for app in existing_apps
            if app.get("implementation") == arr_service.prowlarr_implementation
            or app.get("name") == arr_service.display_name
        ),
        None,
    )

    if existing is not None:
        desired_values = field_value_map(payload["fields"])
        current_values = field_value_map(existing.get("fields", []))
        same_fields = all(current_values.get(name) == value for name, value in desired_values.items())
        if existing.get("enable") and existing.get("syncLevel") == payload["syncLevel"] and same_fields:
            log(f"Prowlarr link for {arr_service.display_name} already matches the desired state")
            return

        payload["id"] = existing["id"]
        prowlarr_api.upsert_application(payload, existing["id"])
        log(f"Updated Prowlarr link for {arr_service.display_name}")
        return

    prowlarr_api.upsert_application(payload, None)
    log(f"Created Prowlarr link for {arr_service.display_name}")


def ensure_arr_integrations(env: dict[str, str], running_services: set[str], dry_run: bool) -> None:
    for arr_service in ARR_SERVICES:
        api_key = env.get(arr_service.api_key_env, "")
        if arr_service.service_name not in running_services:
            continue
        if not api_key:
            log(f"Skipping {arr_service.display_name} because {arr_service.api_key_env} is empty")
            continue

        arr_api = ArrApi(arr_service, api_key)
        ensure_arr_root_folder(arr_api, env, dry_run)
        ensure_arr_download_client(arr_api, env, dry_run)


def ensure_prowlarr_integrations(env: dict[str, str], running_services: set[str], dry_run: bool) -> None:
    if "prowlarr" not in running_services:
        log("Skipping Prowlarr automation because the service is not running")
        return

    prowlarr_key = env.get("PROWLARR_API_KEY", "")
    if not prowlarr_key:
        log("Skipping Prowlarr automation because PROWLARR_API_KEY is empty")
        return

    prowlarr_api = ProwlarrApi(prowlarr_key)
    for arr_service in ARR_SERVICES:
        if arr_service.service_name not in running_services:
            continue
        if not env.get(arr_service.api_key_env, ""):
            continue
        ensure_prowlarr_application(prowlarr_api, arr_service, env, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description="Automate app-to-app connections for the Docker Compose NAS stack.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing anything")
    parser.add_argument("--skip-qbittorrent", action="store_true", help="Skip qBittorrent path and category updates")
    parser.add_argument("--skip-arr", action="store_true", help="Skip Sonarr/Radarr/Lidarr root folders and download clients")
    parser.add_argument("--skip-prowlarr", action="store_true", help="Skip Prowlarr application links")
    args = parser.parse_args()

    env = parse_env_file(ROOT_DIR / ".env.example")
    env.update(parse_env_file(ROOT_DIR / ".env"))
    running_services = compose_running_services()

    if not args.skip_qbittorrent:
        ensure_qbittorrent_paths_and_categories(env, running_services, args.dry_run)

    if not args.skip_arr:
        ensure_arr_integrations(env, running_services, args.dry_run)

    if not args.skip_prowlarr:
        ensure_prowlarr_integrations(env, running_services, args.dry_run)

    log("App connection automation complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())