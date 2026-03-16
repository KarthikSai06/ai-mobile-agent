import subprocess
import logging

logger = logging.getLogger(__name__)

class AdbController:
    """Handles execution of ADB commands."""
    
    def __init__(self, adb_path="adb"):
        self.adb_path = adb_path

    def run_cmd(self, *args) -> str:
        """Executes an adb command and returns the output as a string."""
        cmd = [self.adb_path] + list(args)
        try:
            # Capture output and check for errors
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding='utf-8', errors='replace')
            return result.stdout.strip()
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
            
        lines = output.strip().split("\n")[1:] # Skip 'List of devices attached'
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
        # Look for the line containing mCurrentFocus
        for line in output.splitlines():
            if "mCurrentFocus" in line:
                # Output looks like: mCurrentFocus=Window{... u0 org.telegram.messenger/org.telegram.ui.LaunchActivity}
                if "/" in line:
                    parts = line.split(" ")
                    for part in parts:
                        if "/" in part:
                            # Extract package name before the /
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
