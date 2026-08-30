# Contributing to LifeLog

## Development Workflow

LifeLog uses **trunk-based development** with pull requests.

### Getting Started

1. **Fork** the repository (external contributors) or **clone** (maintainers):
   ```bash
   git clone https://github.com/dlgreenwald/lifelog.git
   cd lifelog
   ```

2. **Set up your environment.** See [README.md](README.md#development) for per-component setup.

3. **Create a branch** from `main`:
   ```bash
   git pull origin main
   git checkout -b feature/your-description
   ```

4. **Make changes.** Follow the conventions in [AGENTS.md](AGENTS.md).

5. **Run tests** before pushing:
   ```bash
   # Quick check — server tests
   cd server && .venv/bin/python -m pytest tests/ -q
   # Dashboard tests
   cd dashboard && npx vitest run
   # Firmware tests
   cd firmware-ota && pio test -e test
   ```

6. **Push and open a PR** against `main`.

### PR Guidelines

- **Title format:** Use [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:` — this becomes the squash commit message
- **Keep PRs small.** If a PR touches more than ~400 lines, consider splitting it
- **Describe what and why.** Link to issues if applicable
- **All CI must pass** before merge
- **Squash merge** — one commit per PR, clean `main` history

### Branch Naming

All work goes on `feature/` branches with descriptive kebab-case names:

| Example | Use case |
|---------|----------|
| `feature/battery-gauge` | New functionality |
| `feature/upload-timeout-retry` | Bug fix |
| `feature/update-python-deps` | Tooling/deps |

### Code Style

- **Python:** Ruff linter, type annotations required, `async/await` throughout
- **TypeScript:** Strict mode, no `any`, `import type` for type-only imports
- **C++ (firmware):** PlatformIO conventions, Unity test framework

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add battery fuel gauge to device status
fix: resolve race condition in session finalization
chore: upgrade whisperx to 0.19
docs: update architecture diagram for job API
test: add worker edge case coverage
refactor: extract shared encryption helpers
```

### Reporting Issues

Open a GitHub issue with:
- Clear title and description
- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Environment details (OS, Python version, Node version, hardware for firmware issues)

### License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
