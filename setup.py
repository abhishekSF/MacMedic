from setuptools import find_packages, setup

APP = ["MacMedic.py"]

OPTIONS = {
    "argv_emulation": False,
    "packages": ["rumps", "psutil"],
    "plist": {
        "CFBundleName": "MacMedic",
        "CFBundleDisplayName": "MacMedic",
        "CFBundleIdentifier": "com.macmedic.app",
        "CFBundleVersion": "0.2.0",
        "CFBundleShortVersionString": "0.2.0",
        "LSUIElement": True,
        "NSHumanReadableCopyright": "MacMedic — lightweight monitor and cleanup tool.",
    },
}

setup(
    app=APP,
    name="MacMedic",
    version="0.2.0",
    description="Lightweight macOS menu bar monitor and cleanup tool",
    packages=find_packages(exclude=["tests"]),
    options={"py2app": OPTIONS},
)
