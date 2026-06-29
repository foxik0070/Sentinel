import importlib.util
import fnmatch
import re
import os
import sys
from . import config, utils

"""
Sentinel Plugin Manager v2026.05.001
Handles dynamic imports from absolute paths and line dispatching to agnostic plugins.
"""

active_plugins = []

def load_plugins():
    """Initializes plugins based on config.DETECTORS and config.PLUGIN_DIR."""
    global active_plugins
    active_plugins.clear()

    if not config.DETECTORS:
        utils.log_message("PluginManager: No detectors defined in config.yaml.")
        return

    # Zajištění, že kořenový adresář /opt/Sentinel je v systémové cestě
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    plugin_dir = getattr(config, "PLUGIN_DIR", os.path.join(config.SCRIPT_DIR, "plugins"))

    for det_conf in config.DETECTORS:
        if not det_conf.get("enabled", True):
            continue

        p_name = det_conf.get("plugin")
        pattern = det_conf.get("match_pattern")
        
        if not p_name or not pattern:
            continue

        plugin_path = os.path.join(plugin_dir, f"{p_name}.py")

        if not os.path.exists(plugin_path):
            utils.log_message(f"[!] PluginManager: Plugin file not found at '{plugin_path}'")
            continue

        try:
            # ---> KLÍČOVÁ OPRAVA: Simulace oficiálního balíčku
            # Přinutíme Python věřit, že plugin je součástí "sentinel.plugins"
            full_module_name = f"sentinel.plugins.{p_name}"
            
            spec = importlib.util.spec_from_file_location(full_module_name, plugin_path)
            module = importlib.util.module_from_spec(spec)
            
            # Zaregistrování do globálního slovníku – DÍKY TOMU FUNGUJÍ RELATIVNÍ IMPORTY (from . import base)
            sys.modules[full_module_name] = module
            
            spec.loader.exec_module(module)

            plugin_class = getattr(module, "Detector")
            instance = plugin_class(name=p_name, config_params=det_conf.get("params", {}))
            
            regex = re.compile(fnmatch.translate(pattern))
            active_plugins.append((regex, instance))
            
            utils.log_message(f"PluginManager: Loaded '{p_name}' for '{pattern}'")
            
        except AttributeError as e:
             utils.log_message(f"[!] PluginManager: Plugin '{p_name}' is missing 'Detector' class: {e}")
        except Exception as e:
            utils.log_message(f"[!] PluginManager: Error loading '{p_name}': {e}")

def dispatch(file_path: str, lines: list):
    """Dispatches lines to all plugins matching the file pattern."""
    fname = os.path.basename(file_path)
    for regex, plugin in active_plugins:
        if regex.match(fname):
            try:
                plugin.process(lines, file_path)
            except Exception as e:
                utils.log_message(f"[!] Runtime error in plugin {plugin.name}: {e}")
