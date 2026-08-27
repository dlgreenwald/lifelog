# scripts/copy_compiledb.py
# Post-build: copy compile_commands.json to project root for clang.
# Generate first with: pio run -e <env> -t compiledb
Import("env")
import shutil
from pathlib import Path

project_dir = Path(env["PROJECT_DIR"])
env_name = env["PIOENV"]
build_dir = project_dir / ".pio" / "build" / env_name

src = build_dir / "compile_commands.json"
dst = project_dir / "compile_commands.json"

if src.exists():
    shutil.copy2(src, dst)
    print(f"compile_commands.json copied to project root ({env_name})")
else:
    print(f"compile_commands.json not found — run: pio run -e {env_name} -t compiledb")
