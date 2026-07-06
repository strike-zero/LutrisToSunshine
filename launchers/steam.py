from PIL import Image
from io import BytesIO
import requests
import datetime
import calendar
from config.constants import DEFAULT_IMAGE
import os
import re
from typing import Tuple, List, Optional
from utils.utils import run_command
from utils.steamgriddb import download_image_from_steamgriddb
from sunshine.sunshine import save_cover_image

STEAM_FLATPAK_ID = "com.valvesoftware.Steam"

def detect_steam_installation() -> Tuple[bool, str]:
    """Detect if Steam is installed and how."""
    # Check for Flatpak installation
    if run_command(f"flatpak list | grep {STEAM_FLATPAK_ID}").returncode == 0:
        return True, "flatpak"
    # Check for native installation
    elif run_command("which steam").returncode == 0:
        return True, "native"
    else:
        return False, ""

def get_steam_root(installation_type: str) -> str:
    """Get the Steam root directory based on installation type."""
    if installation_type == "flatpak":
        return os.path.expanduser("~/.var/app/com.valvesoftware.Steam/.steam/steam")
    else:
        return os.path.expanduser("~/.steam/steam")

def get_steam_id(steam_root: str) -> str:
    """Get the user's SteamID32 (AccountID)."""
    STEAM64_BASE = 76561197960265728

    vdf_path = os.path.join(steam_root, "config", "loginusers.vdf")
    if not os.path.exists(vdf_path):
        print("Please ensure that Steam is logged in before running this application.")
        return '0'

    current_steam64 = None

    try:
        with open(vdf_path, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                
                match = re.match(r'^"(7656\d{13})"$', line)
                if match:
                    current_steam64 = match.group(1)
                    
                if '"MostRecent"' in line and '"1"' in line:
                    return int(current_steam64) - STEAM64_BASE

        return '0'
    except Exception as e:
        print(f"Unable to retrive SteamID32: {e}")
        return '0'

def parse_vdf_value(line: str) -> Optional[str]:
    """Parse a VDF value from a line like '"key" "value"'."""
    match = re.match(r'^\s*"[^"]*"\s*"([^"]*)"', line)
    return match.group(1) if match else None

def parse_libraryfolders(vdf_path: str) -> List[str]:
    """Parse libraryfolders.vdf to get library paths."""
    if not os.path.exists(vdf_path):
        return []
    
    paths = []
    with open(vdf_path, 'r') as f:
        content = f.read()
    
    # Simple parsing for library folders
    # Look for "path" entries
    for match in re.finditer(r'"path"\s*"([^"]*)"', content):
        paths.append(match.group(1))
    
    return paths

def parse_appmanifest(manifest_path: str) -> Optional[Tuple[str, str]]:
    """Parse appmanifest_*.acf to get appid and name."""
    if not os.path.exists(manifest_path):
        return None
    
    appid = None
    name = None
    with open(manifest_path, 'r') as f:
        for line in f:
            if '"appid"' in line:
                appid = parse_vdf_value(line)
            elif '"name"' in line:
                name = parse_vdf_value(line)
            if appid and name:
                break
    
    if appid and name:
        return appid, name
    return None

def list_steam_games() -> List[Tuple[str, str]]:
    """List all Steam games."""
    installed, installation_type = detect_steam_installation()
    if not installed:
        return []
    
    steam_root = get_steam_root(installation_type)
    libraryfolders_path = os.path.join(steam_root, "config", "libraryfolders.vdf")
    
    library_paths = parse_libraryfolders(libraryfolders_path)
    if not library_paths:
        # Fallback to default steamapps
        library_paths = [os.path.join(steam_root, "steamapps")]
    
    games = []
    exclude_patterns = ["proton", "steam linux runtime", "steamworks common", "steamvr"]
    for lib_path in library_paths:
        steamapps_path = os.path.join(lib_path, "steamapps")
        if os.path.exists(steamapps_path):
            for filename in os.listdir(steamapps_path):
                if filename.startswith("appmanifest_") and filename.endswith(".acf"):
                    manifest_path = os.path.join(steamapps_path, filename)
                    result = parse_appmanifest(manifest_path)
                    if result:
                        appid, name = result
                        # Filter out non-game items
                        if not any(name.lower().startswith(pattern) for pattern in exclude_patterns):
                            games.append((appid, name))
    
    return games

def get_steam_command() -> str:
    """Get the command to run Steam."""
    installed, installation_type = detect_steam_installation()
    if not installed:
        return ""
    
    if installation_type == "flatpak":
        return f"flatpak run {STEAM_FLATPAK_ID}"
    else:
        return "steam"

def download_image_from_steam_cdn(appid: str, game_name: str, steamgriddb_api_key: str) -> str:
    """Download game cover image from Steam CDN, or custom cover from Steam library, with fallback to SteamGridDB."""
    installed, installation_type = detect_steam_installation()
    if not installed:
        if steamgriddb_api_key:
            return download_image_from_steamgriddb(game_name, steamgriddb_api_key)
        else:
            return DEFAULT_IMAGE
    
    steam_root = get_steam_root(installation_type)
    
    # Use user customized cover from Steam library if available
    custom_capsule_file = os.path.join(steam_root, "userdata", get_steam_id(steam_root), "config", "grid", f"{appid}p")
    custom_capsule_png = f"{custom_capsule_file}.png"
    custom_capsule_jpg = f"{custom_capsule_file}.jpg"

    if os.path.exists(custom_capsule_png) and os.path.exists(custom_capsule_jpg):
        if os.path.getmtime(custom_capsule_png) > os.path.getmtime(custom_capsule_jpg):
            capsule_path = custom_capsule_png
        else:
            capsule_path = custom_capsule_jpg
    elif os.path.exists(custom_capsule_png):
        capsule_path = custom_capsule_png
    elif os.path.exists(custom_capsule_jpg):
        capsule_path = custom_capsule_jpg
        
    if capsule_path:
        return save_cover_image(capsule_path, game_name)
  
    # Find the half-res covers from Steam library
    app_library_path = os.path.join(steam_root, "appcache", "librarycache", appid)
    if os.path.isdir(app_library_path):
        for root, dirs, files in os.walk(app_library_path):     
            if "library_capsule.jpg" in files:
                capsule_path = os.path.join(root, "library_capsule.jpg")
                break
            elif "library_600x900.jpg" in files:
                capsule_path = os.path.join(root, "library_600x900.jpg")
                break
    
    # Try to download the full-res cover from Steam CDN, else use half-res from Steam library
    if capsule_path:
        steam_cdn = "https://shared.steamstatic.com/store_item_assets/steam/apps"
        file_path = capsule_path.removeprefix(app_library_path).replace("\\","/").replace(".jpg", "_2x.jpg")
        timestamp = calendar.timegm(datetime.now().timetuple())
        url = f"{steam_cdn}/{appid}/{file_path}?t={timestamp}"
        
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        if len(response.content) < 500:
            return save_cover_image(capsule_path, game_name)

        save_path = get_cover_image_path(game_name)
        image = Image.open(BytesIO(response.content))
        image = image.convert("P", palette=Image.ADAPTIVE, colors=256)
        image.save(save_path, "PNG", optimize=True)
        return save_path
    except Exception:
        return save_cover_image(capsule_path, game_name)
    
    # Last resort, download from SteamGridDB
    if steamgriddb_api_key:
        return download_image_from_steamgriddb(game_name, steamgriddb_api_key)
    else:
        return DEFAULT_IMAGE