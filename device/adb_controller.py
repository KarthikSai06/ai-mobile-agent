import subprocess
import logging

logger = logging.getLogger(__name__)

# Default timeout for ADB commands (seconds).
# uiautomator dump can hang on fullscreen video/ad screens.
ADB_TIMEOUT = 15

class AdbController:
    """Handles execution of ADB commands."""
    
    def __init__(self, adb_path="adb"):
        self.adb_path = adb_path

    def run_cmd(self, *args, timeout: int = None) -> str:
        """Executes an adb command and returns the output as a string.
        
        Args:
            *args: ADB command arguments.
            timeout: Max seconds to wait. Defaults to ADB_TIMEOUT.
        """
        if timeout is None:
            timeout = ADB_TIMEOUT
        cmd = [self.adb_path] + list(args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True,
                encoding='utf-8', errors='replace', timeout=timeout
            )
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.warning(f"ADB command timed out after {timeout}s: {' '.join(cmd)}")
            return ""
        except subprocess.CalledProcessError as e:
            logger.error(f"ADB command failed: {' '.join(cmd)}")
            logger.error(f"Error output: {e.stderr}")
            return ""
        except FileNotFoundError:
            logger.error(f"ADB executable not found at {self.adb_path}. Please install ADB and add it to your PATH.")
            return ""

    def get_devices(self) -> list:
        """Returns a list of connected device IDs."""
        output = self.run_cmd("devices")
        if not output:
            return []
            
        lines = output.strip().split("\n")[1:]                                  
        devices = []
        for line in lines:
            if "\tdevice" in line:
                devices.append(line.split("\t")[0].strip())
        return devices

    def get_current_focus(self, device_id: str = None) -> str:
        """Returns the package name of the currently focused activity."""
        cmd = []
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", "dumpsys", "window"])
        
        output = self.run_cmd(*cmd)
                                                    
        for line in output.splitlines():
            if "mCurrentFocus" in line:
                                                                                                                       
                if "/" in line:
                    parts = line.split(" ")
                    for part in parts:
                        if "/" in part:
                                                               
                            return part.split("/")[0].split("{")[-1].split("}")[0].strip()
        return ""

    def list_packages(self, filter_str: str = "", device_id: str = None) -> list:
        """Returns a list of installed packages, optionally filtered."""
        cmd = []
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(["shell", "pm", "list", "packages"])
            
        output = self.run_cmd(*cmd)
        if not output:
            return []
            
        packages = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                package_name = line.replace("package:", "").strip()
                if not filter_str or filter_str.lower() in package_name.lower():
                    packages.append(package_name)
        return packages

    def take_screenshot(self, filename: str, device_id: str = None) -> bool:
        """Takes a screenshot of the device and saves it to the specified path."""
        import os
        sdcard_path = "/sdcard/screen_dump.png"
        
                                      
        cmd1 = []
        if device_id:
            cmd1.extend(["-s", device_id])
        cmd1.extend(["shell", "screencap", "-p", sdcard_path])
        self.run_cmd(*cmd1)
        
                                             
        cmd2 = []
        if device_id:
            cmd2.extend(["-s", device_id])
        cmd2.extend(["pull", sdcard_path, filename])
        self.run_cmd(*cmd2)
        
        return os.path.exists(filename)
