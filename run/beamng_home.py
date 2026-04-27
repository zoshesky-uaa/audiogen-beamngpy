import os
import re
import string
from pathlib import Path


BEAMNG_BINARY_PATHS = (
    "BeamNG.tech.exe",
    "BeamNG.drive.exe",
    os.path.join("Bin64", "BeamNG.tech.x64.exe"),
    os.path.join("Bin64", "BeamNG.x64.exe"),
    os.path.join("Bin64", "BeamNG.drive.x64.exe"),
)

STEAM_LIBRARY_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam",
)


class BeamNGHomeNotFound(RuntimeError):
    pass


def has_beamng_binary(home):
    if not home:
        return False
    home_path = Path(home)
    return any((home_path / binary_path).is_file() for binary_path in BEAMNG_BINARY_PATHS)


def resolve_beamng_home(configured_home=None):
    tried = []
    for candidate in _unique_paths(_candidate_paths(configured_home)):
        tried.append(candidate)
        if has_beamng_binary(candidate):
            return str(candidate)

    locations = "\n".join(f"  - {path}" for path in tried) or "  - <none>"
    binaries = ", ".join(BEAMNG_BINARY_PATHS)
    raise BeamNGHomeNotFound(
        "No BeamNG installation with a launch binary was found.\n"
        "Checked:\n"
        f"{locations}\n"
        f"Expected one of these files in the BeamNG home folder: {binaries}"
    )


def _candidate_paths(configured_home):
    yield configured_home
    yield os.environ.get("BEAMNG_LOCATION")
    yield os.environ.get("BEAMNG_HOME")
    yield from _beamng_homes_from_logs()
    yield from _registry_candidates()
    yield from _steam_candidates()
    yield from _user_profile_candidates()
    yield from _nearby_candidates()
    yield from _common_install_candidates()


def _unique_paths(paths):
    seen = set()
    for path in paths:
        normalized = _normalize_path(path)
        if normalized is None:
            continue
        key = os.path.normcase(str(normalized))
        if key in seen:
            continue
        seen.add(key)
        yield normalized


def _normalize_path(path):
    if path is None:
        return None
    value = str(path).strip().strip("\"'")
    if not value:
        return None
    return Path(os.path.expandvars(os.path.expanduser(value)))


def _common_install_candidates():
    names = ("BeamNG.tech", "BeamNG.drive")
    roots = []

    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:\\")
            if root.exists():
                roots.append(root)
    else:
        roots.extend((Path.home(), Path("/opt"), Path("/usr/local"), Path.cwd()))

    for root in roots:
        for name in names:
            yield root / name

        yield from _matching_child_dirs(root, "beamng")

        for folder_name in ("Program Files", "Program Files (x86)", "Games", "SteamLibrary"):
            folder = root / folder_name
            for name in names:
                yield folder / name
            yield from _matching_child_dirs(folder, "beamng")


def _nearby_candidates():
    for parent in (Path.cwd(), *Path.cwd().parents):
        yield parent / "BeamNG.tech"
        yield parent / "BeamNG.drive"
        yield from _matching_child_dirs(parent, "beamng")


def _user_profile_candidates():
    user_folders = ("Downloads", "Desktop", "Documents", "Games")
    for folder_name in user_folders:
        folder = Path.home() / folder_name
        yield folder / "BeamNG.tech"
        yield folder / "BeamNG.drive"
        yield from _matching_child_dirs(folder, "beamng")


def _steam_candidates():
    for steam_root in STEAM_LIBRARY_CANDIDATES:
        yield from _steam_library_candidates(steam_root)

    for library_root in _steam_libraries_from_vdf():
        yield from _steam_library_candidates(library_root)

    if os.name == "nt":
        for letter in string.ascii_uppercase:
            yield from _steam_library_candidates(Path(f"{letter}:\\SteamLibrary"))


def _steam_library_candidates(library_root):
    common = library_root / "steamapps" / "common"
    yield common / "BeamNG.drive"
    yield common / "BeamNG.tech"
    yield from _matching_child_dirs(common, "beamng")


def _steam_libraries_from_vdf():
    for steam_root in STEAM_LIBRARY_CANDIDATES:
        library_file = steam_root / "steamapps" / "libraryfolders.vdf"
        if not library_file.is_file():
            continue
        try:
            content = library_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in re.finditer(r'"path"\s+"([^"]+)"', content):
            yield Path(match.group(1).replace("\\\\", "\\"))


def _registry_candidates():
    if os.name != "nt":
        return

    try:
        import winreg
    except ImportError:
        return

    roots = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for root, subkey in roots:
        try:
            with winreg.OpenKey(root, subkey) as uninstall_key:
                for index in range(winreg.QueryInfoKey(uninstall_key)[0]):
                    try:
                        app_key_name = winreg.EnumKey(uninstall_key, index)
                        with winreg.OpenKey(uninstall_key, app_key_name) as app_key:
                            display_name = _registry_value(winreg, app_key, "DisplayName")
                            if display_name and "beamng" in display_name.lower():
                                install_location = _registry_value(winreg, app_key, "InstallLocation")
                                display_icon = _registry_value(winreg, app_key, "DisplayIcon")
                                yield install_location
                                if display_icon:
                                    yield Path(display_icon.split(",", 1)[0]).parent
                    except OSError:
                        continue
        except OSError:
            continue


def _registry_value(winreg, key, name):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _beamng_homes_from_logs():
    log_dirs = [
        Path.cwd() / "beamngpy" / "current",
        Path(os.environ.get("LOCALAPPDATA", "")) / "BeamNG",
    ]

    for log_dir in log_dirs:
        if not log_dir.exists():
            continue
        try:
            log_files = list(log_dir.rglob("beamng-launcher*.log"))
        except OSError:
            continue
        for log_file in log_files:
            try:
                content = log_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            yield from _beamng_homes_from_log_text(content)


def _beamng_homes_from_log_text(content):
    for match in re.finditer(r"launcher command line \[\d+\]:\s+(.+?BeamNG\.(?:tech|drive)(?:\.x64)?\.exe)", content):
        yield Path(match.group(1)).parent


def _matching_child_dirs(parent, prefix):
    if not parent.is_dir():
        return
    try:
        for child in parent.iterdir():
            if child.is_dir() and child.name.lower().startswith(prefix):
                yield child
    except OSError:
        return
