"""Language and file type definitions for the Source Stitcher application."""

from typing import Dict, List


def get_language_extensions() -> Dict[str, List[str]]:
    """Return the comprehensive language extensions dictionary."""
    return {
        "Python": [
            ".py",
            ".pyw",
            ".pyx",
            ".pyi",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "pyproject.toml",
            "pipfile",
        ],
        "JavaScript/TypeScript": [
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".mjs",
            ".cjs",
            "package.json",
            "package-lock.json",
            "yarn.lock",
        ],
        "Web Frontend": [
            ".html",
            ".htm",
            ".css",
            ".scss",
            ".sass",
            ".less",
            ".vue",
            ".svelte",
            ".astro",
        ],
        "Java/Kotlin": [
            ".java",
            ".kt",
            ".kts",
            ".gradle",
            "pom.xml",
            "build.gradle",
            "gradle.properties",
        ],
        "C/C++": [
            ".c",
            ".cpp",
            ".cxx",
            ".cc",
            ".h",
            ".hpp",
            ".hxx",
            ".cmake",
            "makefile",
            "cmakelists.txt",
        ],
        "C#/.NET": [".cs", ".fs", ".vb", ".csproj", ".fsproj", ".vbproj", ".sln"],
        "Ruby": [
            ".rb",
            ".rake",
            ".gemspec",
            ".ru",
            "gemfile",
            "gemfile.lock",
            "rakefile",
        ],
        "PHP": [
            ".php",
            ".phtml",
            ".php3",
            ".php4",
            ".php5",
            "composer.json",
            "composer.lock",
        ],
        "Go": [".go", ".mod", ".sum", "go.mod", "go.sum"],
        "Rust": [".rs", "cargo.toml", "cargo.lock"],
        "Swift/Objective-C": [
            ".swift",
            ".m",
            ".mm",
            ".h",
            "package.swift",
            "podfile",
            "podfile.lock",
        ],
        "Shell Scripts": [".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd"],
        "Config & Data": [
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".xml",
            ".ini",
            ".cfg",
            ".conf",
            ".config",
            ".properties",
            ".plist",
            ".env",
            ".envrc",
        ],
        "Documentation": [
            ".md",
            ".markdown",
            ".rst",
            ".txt",
            ".adoc",
            ".org",
            "readme",
            "changelog",
            "license",
            "authors",
        ],
        "DevOps & CI": [
            ".dockerfile",
            "dockerfile",
            ".dockerignore",
            "docker-compose.yml",
            "docker-compose.yaml",
            ".travis.yml",
            ".gitlab-ci.yml",
            ".github",
            ".circleci",
            ".appveyor.yml",
            ".azure-pipelines.yml",
            "jenkinsfile",
            "vagrantfile",
            ".terraform",
            ".tf",
            ".tfvars",
        ],
        "Version Control": [
            ".gitignore",
            ".gitattributes",
            ".gitmodules",
            ".gitkeep",
        ],
        "Build & Package": [
            # Cross-language build systems
            "makefile",  # Make
            "CMakeLists.txt",
            ".cmake",  # CMake
            ".ninja",  # Ninja
            ".bazel",
            ".bzl",
            "BUILD",  # Bazel / Starlark
            ".buck",  # Buck
            "meson.build",
            "meson_options.txt",
            "build.xml",
            "ivy.xml",  # Ant / Ivy
            "configure.ac",
            "configure.in",  # Autotools
            # JVM (Gradle / Maven / SBT)
            "build.gradle",
            "settings.gradle",
            "gradle.properties",
            "gradlew",
            "gradlew.bat",
            "pom.xml",  # Maven
            "build.sbt",
            ".sbt",  # Scala sbt
            # .NET / NuGet
            ".csproj",
            # Python package management
            "uv.lock",
            ".fsproj",
            ".vbproj",
            "packages.config",
            "nuget.config",
            # Swift Package Manager
            "Package.swift",
            "Package.resolved",
            # Go
            "go.mod",
            "go.sum",
            "go.work",
            "go.work.sum",
            # Rust
            "Cargo.toml",
            "Cargo.lock",
            # PHP / Composer
            "composer.json",
            "composer.lock",
            # Ruby / Bundler
            "Gemfile",
            "Gemfile.lock",
            "gemfile",
            "gemfile.lock",
            "rakefile",
            # Python packaging
            "pyproject.toml",  # PEP 517/518 (Poetry, Hatch, etc.)
            "Pipfile",
            "Pipfile.lock",  # Pipenv
            "poetry.lock",  # Poetry
            "requirements.txt",  # classic
            "requirements-dev.txt",
            "requirements-test.txt",
            "setup.py",
            "setup.cfg",
            "environment.yml",  # Conda
            # JavaScript / TypeScript / Node ecosystem
            # npm
            "package.json",
            "package-lock.json",
            "npm-shrinkwrap.json",
            # Yarn
            "yarn.lock",
            ".yarnrc",
            ".yarnrc.yml",
            # pnpm
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            ".pnpmfile.cjs",
            # bun
            "bun.lockb",
            # monorepo / workspace tools
            "rush.json",
            "lerna.json",  # Rush, Lerna
            "turbo.json",
            "turbo.yaml",  # Turborepo
            # Other language-specific lock / build files
            "flake.lock",
            "flake.nix",  # Nix flakes
            "build.pyz",  # PEX / Pants
        ],
        "Other Text Files": [
            "*other*"
        ],  # Special category for unmatched text files
    }