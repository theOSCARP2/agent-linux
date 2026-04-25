from setuptools import setup, find_packages

setup(
    name="agent-linux",
    version="1.0.0",  # managed by bump2version
    description="AI-powered Linux server administration agent",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "anthropic",
        "psutil",
        "docker",
        "rich",
        "pyyaml",
    ],
    entry_points={
        "console_scripts": [
            "agent-linux=cli.agent_linux_cli:main",
        ],
    },
)
