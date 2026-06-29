import os
import re
from setuptools import setup, find_packages

# --- Helper functions ---
def get_version():
    """
    Nacte verzi ze souboru sentinel/config.py bez nutnosti importovat balicek.
    Pouziva regex pro nalezeni radku: VERSION = "..."
    """
    version_file = os.path.join("sentinel", "config.py")
    with open(version_file, "r", encoding="utf-8") as f:
        content = f.read()
        mo = re.search(r"^VERSION\s*=\s*['\"]([^'\"]+)['\"]", content, re.MULTILINE)
        if mo:
            return mo.group(1)
    raise RuntimeError(f"Unable to find version string in {version_file}.")

def get_long_description():
    """Nacte obsah README.md pro dlouhy popis balicku."""
    try:
        with open("README.md", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Sentinel - AI Log Monitor & Analyzer"

def get_dynamic_requirements():
    """
    Dynamicky upravi zavislosti podle operacniho systemu.
    ChromaDB vyzaduje SQLite >= 3.35.0. Starsi OS (RHEL 8/9) potrebuji pysqlite3-binary.
    RHEL 10 a moderni Ubuntu/Debian maji SQLite dostatecne novy.
    """
    base_reqs = [
        "pyyaml",
        "python-docx",
        "openpyxl",
        "requests",
        "watchdog",
        "markdown",
        "paramiko",
        "flask",
        "flask-socketio",
        "numpy",
        "flask-ldap3-login",
        "chromadb"
    ]

    try:
        with open("/etc/os-release") as f:
            os_data = f.read().lower()
        
        # Detekce RHEL / Rocky / AlmaLinux 8 a 9
        is_rhel_8_9 = any(x in os_data for x in ['release 8', 'release 9', 'version="8', 'version="9']) and \
                      any(x in os_data for x in ['rhel', 'centos', 'rocky', 'almalinux'])
        
        # Detekce starsich Debian/Ubuntu (pred rokem 2022)
        is_old_deb = ('debian' in os_data and ('bullseye' in os_data or 'buster' in os_data))
        is_old_ubu = ('ubuntu' in os_data and ('focal' in os_data or 'bionic' in os_data))

        # Pokud jsme na starem OS, pridame workaround pro SQLite
        if is_rhel_8_9 or is_old_deb or is_old_ubu:
            base_reqs.append("pysqlite3-binary")
            
    except Exception:
        # V pripade selhani detekce pro jistotu pridame
        base_reqs.append("pysqlite3-binary")

    return base_reqs

# --- Setup configuration ---
setup(
    name="sentinel",
    version=get_version(),
    description="AI Log Monitor & Analyzer for Linux Infrastructure",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    
    author="foxik0070",
    author_email="foxik0070@gmail.com",
    maintainer="foxik0070",
    
    url="https://github.com/sentinel-commander/sentinel",
    project_urls={
        "Bug Tracker": "https://github.com/sentinel-commander/sentinel/issues",
        "Source Code": "https://github.com/sentinel-commander/sentinel",
    },

    packages=find_packages(),
    include_package_data=True,
    
    python_requires=">=3.8",
    install_requires=get_dynamic_requirements(),

    entry_points={
        'console_scripts': [
            'sentinel=sentinel.__main__:main',
        ],
    },

    license="MIT",

    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: System Administrators",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Topic :: System :: Monitoring",
    ],
)
